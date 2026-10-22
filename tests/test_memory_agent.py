import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from research_assistant.chat import build_chat_graph, initialize_chat
from research_assistant.memory_tools import MemoryContext
from research_assistant.user_memory import open_memory_store, get_profile, list_notes, MemoryError
from test_chat import FakeModel, materials


def memory_call(name, data, identifier='call-memory'):
    return {'name': name, 'args': data, 'id': identifier}


class MemoryAgentTests(unittest.TestCase):
    def test_runtime_store_path_matches_normalized_chat_binding(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / 'memory.sqlite')
            alias = str(Path(root) / 'alias' / '..' / 'memory.sqlite')
            with open_memory_store(path) as store:
                model = FakeModel([AIMessage('Answer')])
                graph, config, context = self.start(model, store, alias)
                result = graph.invoke({'question': 'Question'}, config, context=context)
                self.assertEqual(result['status'], 'answered')
                self.assertEqual(context.store_path, str(Path(path).resolve()))

    def start(self, model, store, path, user='alice', thread='a', saver=None):
        graph = build_chat_graph(checkpointer=saver or InMemorySaver(), model_factory=lambda: model, store=store)
        config = {'configurable': {'thread_id': thread}}
        initialize_chat(graph, config, materials(), 'checkpoints', user_id=user, store_path=path)
        return graph, config, MemoryContext(user, thread, path)

    def test_real_tool_profile_refresh_cross_thread_and_isolation(self):
        with tempfile.TemporaryDirectory() as root, open_memory_store(str(Path(root) / 'memory.sqlite')) as store:
            path = str(Path(root) / 'memory.sqlite')
            model = FakeModel([AIMessage('', tool_calls=[memory_call('update_profile', {'preferences': {'language': 'English'}})]),
                               AIMessage('Saved')])
            graph, config, context = self.start(model, store, path)
            graph.invoke({'question': 'Измени предпочтение: отвечай на English'}, config, context=context)
            self.assertEqual(get_profile(store, 'alice')['language'], 'English')
            self.assertIn('English', model.contexts[-1][0].content)
            for user in ('alice', 'bob'):
                next_model = FakeModel([AIMessage('Answer')])
                graph, config, context = self.start(next_model, store, path, user=user, thread=user + '-new')
                graph.invoke({'question': 'Question'}, config, context=context)
                self.assertEqual('English' in next_model.contexts[0][0].content, user == 'alice')
            for tool in model.tools[1:]:
                self.assertNotIn('runtime', tool.tool_call_schema.model_json_schema()['properties'])

    def test_note_idempotency_resume_and_unauthorized_calls(self):
        with tempfile.TemporaryDirectory() as root, open_memory_store(str(Path(root) / 'memory.sqlite')) as store:
            path = str(Path(root) / 'memory.sqlite')
            model = FakeModel([AIMessage('', tool_calls=[memory_call('save_note', {'note': {'text': 'LangGraph data'}})]),
                               MemoryError('Model temporarily unavailable'), AIMessage('Saved')])
            graph, config, context = self.start(model, store, path)
            with self.assertRaises(MemoryError):
                graph.invoke({'question': 'Запомни: LangGraph data'}, config, context=context)
            self.assertEqual(len(list_notes(store, 'alice')), 1)
            graph.invoke(None, config, context=context)
            self.assertEqual(len(list_notes(store, 'alice')), 1)
            for args, question in [({'note': {'text': 'Unwanted'}}, 'Что сказано в отчёте?'),
                                   ({'note': {'text': 'Wrong user'}, 'user_id': 'bob'}, 'Запомни wrong')]:
                model = FakeModel([AIMessage('', tool_calls=[memory_call('save_note', args)]), AIMessage('SUCCESS LIE')])
                graph, config, context = self.start(model, store, path, thread=question)
                result = graph.invoke({'question': question}, config, context=context)
                self.assertNotIn('SUCCESS', result['answer'])
                self.assertEqual(len(list_notes(store, 'alice')), 1)
            self.assertEqual(list_notes(store, 'bob'), [])

    def test_store_failure_cannot_be_claimed_as_success(self):
        with tempfile.TemporaryDirectory() as root, open_memory_store(str(Path(root) / 'memory.sqlite')) as store:
            path = str(Path(root) / 'memory.sqlite')
            model = FakeModel([AIMessage('', tool_calls=[memory_call('save_note', {'note': {'text': 'Fact'}})]), AIMessage('SUCCESS LIE')])
            graph, config, context = self.start(model, store, path)
            with patch('research_assistant.memory_tools.apply_tool_operation', side_effect=MemoryError('PRIVATE SQL')):
                result = graph.invoke({'question': 'Запомни Fact'}, config, context=context)
            self.assertNotIn('SUCCESS', result['answer'])
            self.assertNotIn('PRIVATE', result['answer'])
            self.assertEqual(list_notes(store, 'alice'), [])

    def test_delete_tool_and_current_budget_selection(self):
        from research_assistant.user_memory import save_note
        from research_assistant.chat_context import ContextBudget, estimate_tokens, tool_cost
        from research_assistant.chat import get_source
        from research_assistant.memory_tools import MEMORY_TOOLS
        from langchain_core.utils.function_calling import convert_to_openai_tool
        with tempfile.TemporaryDirectory() as root, open_memory_store(str(Path(root) / 'memory.sqlite')) as store:
            path = str(Path(root) / 'memory.sqlite')
            ids = [save_note(store, 'alice', {'text': 'LangGraph ' + 'X' * 550}, note_id=f'n{i}') for i in range(3)]
            model = FakeModel([AIMessage('A')])
            budget = ContextBudget(input_tokens=1600, answer_reserve=100, summary_tokens=100)
            graph = build_chat_graph(checkpointer=InMemorySaver(), model_factory=lambda: model,
                                     store=store, context_budget=budget)
            config = {'configurable': {'thread_id': 'budget'}}
            initialize_chat(graph, config, materials(), 'db', user_id='alice', store_path=path)
            context = MemoryContext('alice', 'budget', path)
            graph.invoke({'question': 'LangGraph'}, config, context=context)
            diagnostics = graph.get_state(config).values['memory_diagnostics']['notes']
            self.assertLess(len(diagnostics), 3)
            self.assertEqual(model.contexts[0][-1].content, 'LangGraph')
            self.assertLessEqual(estimate_tokens(model.contexts[0]) + budget.answer_reserve
                + tool_cost([convert_to_openai_tool(t) for t in [get_source, *MEMORY_TOOLS]]), budget.input_tokens)
            model = FakeModel([AIMessage('', tool_calls=[memory_call('delete_note', {'note_id': ids[0]})]), AIMessage('Deleted')])
            graph, config, context = self.start(model, store, path, thread='delete')
            graph.invoke({'question': 'Забудь заметку ' + ids[0]}, config, context=context)
            self.assertNotIn(ids[0], [n['id'] for n in list_notes(store, 'alice')])

    def test_runtime_owner_and_injected_arguments_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as root, open_memory_store(str(Path(root) / 'memory.sqlite')) as store:
            path = str(Path(root) / 'memory.sqlite')
            for extra in ({'runtime': {'user_id': 'bob'}}, {'namespace': ['bob', 'notes']}):
                model = FakeModel([AIMessage('', tool_calls=[memory_call('save_note', {
                    'note': {'text': 'Forbidden'}, **extra})]), AIMessage('SUCCESS LIE')])
                graph, config, context = self.start(model, store, path, thread=str(extra))
                result = graph.invoke({'question': 'Запомни Forbidden'}, config, context=context)
                self.assertNotIn('SUCCESS', result['answer'])
            self.assertEqual(list_notes(store, 'alice'), [])
            self.assertEqual(list_notes(store, 'bob'), [])
            graph, config, context = self.start(FakeModel([]), store, path, thread='wrong-context')
            with self.assertRaises(MemoryError):
                graph.invoke({'question': 'Q'}, config, context=MemoryContext('bob', context.thread_id, path))

    def test_words_of_model_without_tool_are_not_storage_confirmation(self):
        with tempfile.TemporaryDirectory() as root, open_memory_store(str(Path(root) / 'memory.sqlite')) as store:
            path = str(Path(root) / 'memory.sqlite')
            model = FakeModel([AIMessage('Успешно сохранено в память')])
            graph, config, context = self.start(model, store, path)
            result = graph.invoke({'question': 'Запомни LangGraph'}, config, context=context)
            self.assertNotIn('Успешно сохранено', result['answer'])
            self.assertEqual(list_notes(store, 'alice'), [])
