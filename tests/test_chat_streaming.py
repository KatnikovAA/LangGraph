import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from research_assistant.chat import build_chat_graph, initialize_chat, ChatError
from research_assistant.chat_streaming import stream_chat, visible_text
from test_chat import FakeModel, materials


class ChunkModel(BaseChatModel):
    responses: list = Field(default_factory=list)
    contexts: list = Field(default_factory=list)
    streamed: int = 0
    generated: int = 0
    pieces: list[str] = Field(default_factory=lambda: ['Первая ', 'часть'])

    @property
    def _llm_type(self):
        return 'offline-chunks'

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.generated += 1
        self.contexts.append(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage('Обычный ответ'))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.streamed += 1
        self.contexts.append(messages)
        # These are the fake provider's actual incremental emissions, not CLI text splitting.
        yield ChatGenerationChunk(message=AIMessageChunk(content=[{'type': 'reasoning', 'reasoning': 'PRIVATE_REASON'}]))
        for piece in self.pieces:
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if self.responses:
                self.responses.pop(0)()  # Verify visible BEFORE generation finishes.


class StreamingTests(unittest.TestCase):
    def start(self, model):
        graph = build_chat_graph(checkpointer=InMemorySaver(), model_factory=lambda: model)
        config = {'configurable': {'thread_id': 'stream'}}
        initialize_chat(graph, config, materials(), 'db')
        return graph, config

    def test_actual_graph_chunks_namespace_early_delivery_and_no_reinvoke(self):
        from threading import Event
        delivered = Event()
        class ObservedOutput(StringIO):
            def write(self, value):
                result = super().write(value)
                if 'Первая ' in self.getvalue():
                    delivered.set()
                return result
        err = ObservedOutput()
        model = ChunkModel(responses=[lambda: self.assertTrue(delivered.wait(3), 'chunk buffered until completion')])
        graph, config = self.start(model)
        with redirect_stderr(err), patch.object(graph, 'invoke', side_effect=AssertionError('second run')):
            result = stream_chat(graph, {'question': 'Вопрос'}, config)
        self.assertEqual(result['answer'], 'Первая часть')
        self.assertEqual(model.streamed, 1)
        self.assertEqual(model.generated, 0)
        self.assertIn('Предварительный', err.getvalue())
        self.assertNotIn('PRIVATE_REASON', err.getvalue())
        self.assertNotIn('Фрагмент', err.getvalue())
        self.assertEqual(len(graph.get_state(config).values['messages']), 2)

    def test_no_chunks_reports_limitation_and_resume_uses_stream(self):
        model = FakeModel([ChatError('temporary'), AIMessage('Готово')])
        graph, config = self.start(model)
        with self.assertRaises(ChatError):
            graph.invoke({'question': 'Q'}, config)
        err = StringIO()
        with redirect_stderr(err), patch.object(graph, 'invoke', side_effect=AssertionError('invoke')):
            result = stream_chat(graph, None, config)
        self.assertEqual(result['answer'], 'Готово')
        self.assertIn('token streaming провайдера не подтверждён', err.getvalue())
        self.assertEqual(len(graph.get_state(config).values['messages']), 2)

    def test_filter_summary_tool_arguments_and_reasoning(self):
        class Events:
            def stream(self, *args, **kwargs):
                yield (), 'updates', {'context_gate': {'summary_pending': True}}
                yield (), 'messages', (AIMessageChunk('SECRET_SUMMARY'), {'langgraph_node': 'summarize'})
                yield ('run_agent:task',), 'messages', (AIMessageChunk('', tool_call_chunks=[
                    {'name': 'get_source', 'args': 'SECRET_ARGUMENT', 'id': 'call', 'index': 0}]), {'langgraph_node': 'agent'})
                yield ('run_agent:task',), 'updates', {'tools': {'messages': ['SECRET_TOOL']}}
                yield ('run_agent:task',), 'messages', (AIMessageChunk(content=[
                    {'type': 'reasoning', 'reasoning': 'SECRET_REASON'}, {'type': 'text', 'text': 'Видимый'}]),
                    {'langgraph_node': 'agent'})
            def get_state(self, config):
                from types import SimpleNamespace
                return SimpleNamespace(next=(), values={'answer': 'Итог', 'status': 'answered'})
        err = StringIO()
        with redirect_stderr(err):
            self.assertEqual(stream_chat(Events(), {}, {})['answer'], 'Итог')
        self.assertNotIn('SECRET', err.getvalue())
        self.assertIn('Обновляем Summary', err.getvalue())
        self.assertIn('Видимый', err.getvalue())

    def test_actual_summary_model_chunks_are_hidden(self):
        from research_assistant.chat_context import ContextBudget
        agent = ChunkModel()
        summary_model = ChunkModel(pieces=['PRIVATE_SUMMARY'])
        def summarize(messages, config):
            return summary_model.invoke(messages, config=config).text
        graph = build_chat_graph(checkpointer=InMemorySaver(), model_factory=lambda: agent,
                                 summarizer=summarize, context_budget=ContextBudget(summary_threshold=1, recent_turns=1))
        config = {'configurable': {'thread_id': 'summary-stream'}}
        initialize_chat(graph, config, materials(), 'db')
        for i in range(2):
            graph.invoke({'question': f'Q{i}'}, config)
        err = StringIO()
        with redirect_stderr(err):
            stream_chat(graph, {'question': 'Q2'}, config)
        self.assertEqual(summary_model.streamed, 1)
        self.assertIn('Обновляем Summary', err.getvalue())
        self.assertNotIn('PRIVATE_SUMMARY', err.getvalue())
        self.assertEqual(graph.get_state(config).values['summary'], 'PRIVATE_SUMMARY')

    def test_cli_one_json_no_success_on_error_and_budget_flags(self):
        import tempfile
        from pathlib import Path
        from test_chat_session import completed_research
        from research_assistant.cli import main
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            completed_research(db, root)
            for model, expected in [(ChunkModel(), 0), (FakeModel([ChatError('API недоступно')]), 2)]:
                out, err = StringIO(), StringIO()
                with patch('research_assistant.chat.create_model', return_value=model), redirect_stdout(out), redirect_stderr(err):
                    code = main(['--discuss', 'research', '--question', 'Q', '--stream', '--checkpoint-db', db])
                self.assertEqual(code, expected, err.getvalue())
                if expected == 0:
                    result = json.loads(out.getvalue())
                    self.assertEqual(result['answer'], 'Первая часть')
                else:
                    self.assertEqual(out.getvalue(), '')
            for flags in [['--stream'], ['--topic', 'Q', '--stream'], ['--chat', 'x', '--context-budget', '9000'],
                          ['--discuss', 'research', '--question', 'Q', '--context-budget', '-1']]:
                out, err = StringIO(), StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = main(flags + ['--checkpoint-db', db])
                self.assertEqual(code, 2)
                self.assertEqual(out.getvalue(), '')
