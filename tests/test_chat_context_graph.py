import unittest
from unittest.mock import Mock
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from research_assistant.chat import build_chat_graph, initialize_chat, ChatError
from research_assistant.chat_context import ContextBudget
from test_chat import FakeModel, materials, call


class ContextGraphTests(unittest.TestCase):
    def start(self, model, summary, budget=None):
        graph = build_chat_graph(checkpointer=InMemorySaver(), model_factory=lambda: model,
                                 summarizer=summary, context_budget=budget or ContextBudget())
        config = {'configurable': {'thread_id': 'chat'}}
        initialize_chat(graph, config, materials(), 'db')
        return graph, config

    def test_threshold_incremental_summary_and_full_history(self):
        summary = Mock(side_effect=['Первый пересказ', 'Второй пересказ'])
        model = FakeModel([AIMessage('Ответ ' + 'a' * 120) for _ in range(5)])
        graph, config = self.start(model, summary, ContextBudget(summary_threshold=100, recent_turns=1))
        graph.invoke({'question': 'Вопрос 0 ' + 'x' * 120}, config)
        summary.assert_not_called()
        graph.invoke({'question': 'Вопрос 1 ' + 'x' * 120}, config)
        summary.assert_not_called()
        graph.invoke({'question': 'Вопрос 2'}, config)
        state = graph.get_state(config).values
        self.assertEqual(state['summary'], 'Первый пересказ')
        self.assertEqual(len(state['messages']), 6)
        self.assertEqual(state['summarized_through'], state['messages'][1].id)
        self.assertNotIn('Вопрос 0', str([m.content for m in model.contexts[-1][1:]]))
        self.assertIn('Первый пересказ', model.contexts[-1][0].content)
        graph.invoke({'question': 'Вопрос 3'}, config)
        self.assertEqual(summary.call_count, 2)
        second = summary.call_args.args[0]
        self.assertIn('Первый пересказ', second[0].content)
        self.assertIn('Вопрос 1', second[1].content)
        self.assertNotIn('Вопрос 0', second[1].content)

    def test_summary_error_preserves_boundary_and_resume(self):
        model = FakeModel([AIMessage('a' * 200) for _ in range(3)])
        summary = Mock(side_effect=[ChatError('Summary недоступно'), 'Кратко'])
        graph, config = self.start(model, summary, ContextBudget(summary_threshold=80, recent_turns=1))
        for i in range(2):
            graph.invoke({'question': f'Q{i}'}, config)
        with self.assertRaises(ChatError):
            graph.invoke({'question': 'Q2'}, config)
        state = graph.get_state(config).values
        self.assertEqual(len(state['messages']), 5)
        self.assertIsNone(state['summarized_through'])
        self.assertEqual(len(model.contexts), 2)
        graph.invoke(None, config)
        self.assertEqual(len(graph.get_state(config).values['messages']), 6)

    def test_subgraph_resume_does_not_repeat_tool_or_question(self):
        model = FakeModel([AIMessage('', tool_calls=[call()]), ChatError('временно'), AIMessage('Готово')])
        graph, config = self.start(model, Mock())
        with self.assertRaises(ChatError):
            graph.invoke({'question': 'Вопрос'}, config)
        graph.invoke(None, config)
        history = graph.get_state(config).values['messages']
        self.assertEqual(len(history), 4)
        self.assertEqual(sum(isinstance(m, HumanMessage) for m in history), 1)
        self.assertEqual(sum(isinstance(m, AIMessage) and bool(m.tool_calls) for m in history), 1)
        self.assertEqual(sum(len([m for m in ctx if m.type == 'tool']) for ctx in model.contexts), 2)

    def test_oversized_report_question_and_tool_result_before_next_model(self):
        for mode in ['report', 'question', 'tool']:
            model = FakeModel([AIMessage('', tool_calls=[call()]), AIMessage('A')])
            graph, config = self.start(model, Mock(), ContextBudget(input_tokens=2000, answer_reserve=100, summary_tokens=100))
            if mode != 'question':
                state = graph.get_state(config).values
                update = {'report_markdown': 'R' * 12000} if mode == 'report' else {
                    'sources': [{**state['sources'][0], 'snippet': 'X' * 12000}]}
                graph.update_state(config, update, as_node='finish')
            with self.assertRaises(ChatError):
                graph.invoke({'question': 'Q' * 12000 if mode == 'question' else 'Q'}, config)
            self.assertEqual(len(model.contexts), 1 if mode == 'tool' else 0)

    def test_summary_size_failure_and_trim_without_summary(self):
        summary = Mock(return_value='X' * 3000)
        model = FakeModel([AIMessage('A' * 200) for _ in range(3)])
        graph, config = self.start(model, summary, ContextBudget(summary_threshold=80, recent_turns=1, summary_tokens=100))
        for i in range(2):
            graph.invoke({'question': f'Q{i}'}, config)
        with self.assertRaisesRegex(ChatError, 'Summary'):
            graph.invoke({'question': 'Q2'}, config)
        state = graph.get_state(config).values
        self.assertEqual(state['summary'], '')
        self.assertIsNone(state['summarized_through'])
        self.assertEqual(len(state['messages']), 5)
        model = FakeModel([AIMessage('A' * 1800) for _ in range(5)])
        summary = Mock()
        budget = ContextBudget(input_tokens=2000, answer_reserve=100, summary_threshold=100000, summary_tokens=100)
        graph, config = self.start(model, summary, budget)
        for i in range(5):
            graph.invoke({'question': f'Q{i}'}, config)
        self.assertEqual(len(graph.get_state(config).values['messages']), 10)
        self.assertLess(len(model.contexts[-1]), 10)
        self.assertEqual(model.contexts[-1][-1].content, 'Q4')
        summary.assert_not_called()

    def test_summary_and_subgraph_resume_across_processes(self):
        import json
        import subprocess
        import sys
        import tempfile
        from pathlib import Path
        worker = str(Path(__file__).with_name('context_worker.py'))
        with tempfile.TemporaryDirectory() as root:
            def run(mode):
                process = subprocess.run([sys.executable, worker, mode, str(Path(root) / 'db.sqlite')],
                    capture_output=True, text=True, encoding='utf-8', timeout=30)
                self.assertEqual(process.returncode, 0, process.stderr)
                return json.loads(process.stdout)
            first, second = run('create'), run('continue')
            self.assertEqual(first['count'], 6)
            self.assertEqual(second['count'], 8)
            self.assertNotEqual(first['boundary'], second['boundary'])
            self.assertEqual(second['summary'], 'Новый пересказ')
            run('fail')
            self.assertEqual(run('resume')['count'], 4)

    def test_summary_isolation_and_budget_accounts_for_all_inputs(self):
        from research_assistant.chat_context import estimate_tokens, tool_cost
        from research_assistant.chat import get_source
        from langchain_core.utils.function_calling import convert_to_openai_tool
        saver = InMemorySaver()
        model = FakeModel([AIMessage('A' * 200) for _ in range(4)])
        budget = ContextBudget(input_tokens=2000, answer_reserve=100, summary_threshold=80, recent_turns=1)
        graph = build_chat_graph(checkpointer=saver, model_factory=lambda: model,
                                 summarizer=lambda *args: 'Private summary for A', context_budget=budget)
        a, b = ({'configurable': {'thread_id': name}} for name in ('a', 'b'))
        for config in (a, b):
            initialize_chat(graph, config, materials(), 'db')
        for i in range(3):
            graph.invoke({'question': f'Private question A {i}'}, a)
        self.assertEqual(graph.get_state(a).values['summary'], 'Private summary for A')
        graph.invoke({'question': 'Question B'}, b)
        self.assertEqual(graph.get_state(b).values['summary'], '')
        self.assertIsNone(graph.get_state(b).values['summarized_through'])
        self.assertNotIn('Private', str([m.content for m in model.contexts[-1]]))
        for context in model.contexts:
            self.assertLessEqual(estimate_tokens(context) + tool_cost(convert_to_openai_tool(get_source))
                                 + budget.answer_reserve, budget.input_tokens)
