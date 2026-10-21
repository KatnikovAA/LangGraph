import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolNode


def materials():
    return {'research_thread_id': 'research', 'report_markdown': '# Отчёт\nДанные [S1][S1]',
            'sources': [{'title': 'Документ', 'url': 'https://example.org/docs', 'snippet': 'Фрагмент',
                         'section_indexes': [0]}]}


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.contexts = []
        self.tools = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.contexts.append(list(messages))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def call(source='S1', identifier='call-1', name='get_source'):
    return {'name': name, 'args': {'source_id': source}, 'id': identifier}


class ChatGraphTests(unittest.TestCase):
    def start(self, model, *, thread_id='chat', saver=None):
        from research_assistant.chat import build_chat_graph, initialize_chat
        graph = build_chat_graph(checkpointer=saver or InMemorySaver(), model_factory=lambda: model)
        config = {'configurable': {'thread_id': thread_id}}
        initialize_chat(graph, config, materials(), 'db-path')
        return graph, config

    def test_direct_two_turns_and_multiple_schemas(self):
        model = FakeModel([AIMessage('Первый ответ'), AIMessage('Второй ответ')])
        graph, config = self.start(model)
        result = graph.invoke({'question': 'Первый вопрос'}, config)
        self.assertEqual(result, {'answer': 'Первый ответ', 'status': 'answered'})
        graph.invoke({'question': 'Второй вопрос'}, config)
        history = graph.get_state(config).values['messages']
        self.assertEqual([m.content for m in history], ['Первый вопрос', 'Первый ответ', 'Второй вопрос', 'Второй ответ'])
        self.assertFalse(any(isinstance(m, SystemMessage) for m in history))
        self.assertEqual([type(m) for m in model.contexts[1]], [SystemMessage, HumanMessage, AIMessage, HumanMessage])
        self.assertIn(json.dumps(materials()['report_markdown'], ensure_ascii=False), model.contexts[1][0].content)
        self.assertNotIn('sources', result)
        self.assertNotIn('messages', result)

    def test_actual_toolnode_and_matching_tool_message(self):
        model = FakeModel([AIMessage('', tool_calls=[call()]), AIMessage('По источнику S1: фрагмент')])
        graph, config = self.start(model)
        self.assertIsInstance(graph.nodes['tools'].bound, ToolNode)
        result = graph.invoke({'question': 'Что в S1?'}, config)
        self.assertEqual(result['status'], 'answered')
        tool_messages = [m for m in graph.get_state(config).values['messages'] if isinstance(m, ToolMessage)]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0].tool_call_id, 'call-1')
        self.assertEqual(json.loads(tool_messages[0].content), {'source_id': 'S1', 'title': 'Документ',
                                                             'url': 'https://example.org/docs', 'snippet': 'Фрагмент'})
        self.assertEqual(model.contexts[1][-1], tool_messages[0])
        schema = model.tools[0].tool_call_schema.model_json_schema()
        self.assertEqual(set(schema['properties']), {'source_id'})

    def test_unknown_source_and_tool_are_predictable(self):
        for tool_call in [call('S999'), call(name='arbitrary_tool')]:
            with self.subTest(tool_call=tool_call):
                model = FakeModel([AIMessage('', tool_calls=[tool_call]), AIMessage('Источник не найден')])
                graph, config = self.start(model)
                graph.invoke({'question': 'Источник?'}, config)
                history = graph.get_state(config).values['messages']
                self.assertIsInstance(history[2], ToolMessage)
                self.assertEqual(history[2].tool_call_id, 'call-1')
                if tool_call['name'] == 'get_source':
                    self.assertEqual(json.loads(history[2].content)['error'], 'unknown_source_id')

    def test_tool_state_cannot_be_overridden_by_model_arguments(self):
        malicious = call()
        malicious['args']['state'] = {'sources': [{'title': 'Другой Thread', 'url': 'https://wrong.example', 'snippet': 'Чужие данные'}]}
        model = FakeModel([AIMessage('', tool_calls=[malicious]), AIMessage('Готово')])
        graph, config = self.start(model)
        graph.invoke({'question': 'Прочитай S1'}, config)
        tool_result = graph.get_state(config).values['messages'][2]
        self.assertEqual(json.loads(tool_result.content)['url'], 'https://example.org/docs')

    def test_loop_and_tool_budgets_close_all_calls_and_reset_next_turn(self):
        for responses in [
            [AIMessage('', tool_calls=[call(identifier=f'c{i}')]) for i in range(3)],
            [AIMessage('', tool_calls=[call(identifier=f'c{i}') for i in range(4)])],
            [AIMessage('', tool_calls=[call(identifier=f'a{i}') for i in range(2)]),
             AIMessage('', tool_calls=[call(identifier=f'b{i}') for i in range(2)])],
        ]:
            with self.subTest(responses=responses):
                model = FakeModel(responses + [AIMessage('Следующий ответ')])
                graph, config = self.start(model)
                result = graph.invoke({'question': 'Повторяй вызовы'}, config)
                self.assertEqual(result['status'], 'limited')
                history = graph.get_state(config).values['messages']
                requested = [c['id'] for m in history if isinstance(m, AIMessage) for c in m.tool_calls]
                answered = [m.tool_call_id for m in history if isinstance(m, ToolMessage)]
                self.assertCountEqual(requested, answered)
                self.assertIsInstance(history[-1], AIMessage)
                self.assertFalse(history[-1].tool_calls)
                self.assertLessEqual(graph.get_state(config).values['tool_calls_used'], 3)
                self.assertLessEqual(len(model.contexts), 3)
                self.assertEqual(graph.invoke({'question': 'Новый вопрос'}, config)['status'], 'answered')

    def test_blank_question_invalid_model_response_and_isolated_threads(self):
        from research_assistant.chat import ChatError
        model = FakeModel([AIMessage('A'), AIMessage('B')])
        saver = InMemorySaver()
        first, a = self.start(model, thread_id='a', saver=saver)
        second, b = self.start(model, thread_id='b', saver=saver)
        first.invoke({'question': 'Вопрос A'}, a)
        second.invoke({'question': 'Вопрос B'}, b)
        self.assertNotIn('Вопрос A', [m.content for m in second.get_state(b).values['messages']])
        graph, config = self.start(FakeModel([]))
        with self.assertRaises(ChatError):
            graph.invoke({'question': ' \t '}, config)
        for response in [None, AIMessage(''), AIMessage('', tool_calls=[call(identifier='')])]:
            graph, config = self.start(FakeModel([response]))
            with self.assertRaises(ChatError):
                graph.invoke({'question': 'Вопрос'}, config)
