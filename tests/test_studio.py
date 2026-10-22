"""Server persistence ownership and offline Studio workflow."""

import asyncio
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from research_assistant.graph import build_graph


class StudioTests(unittest.TestCase):
    def test_server_owns_checkpointer_but_cli_still_requires_one(self):
        with self.assertRaisesRegex(ValueError, 'checkpointer'):
            build_graph(review=True)
        graph = build_graph(review=True, persistence='server')
        self.assertIsNone(graph.checkpointer)
        with self.assertRaisesRegex(ValueError, 'server'):
            build_graph(review=True, persistence='server', checkpointer=InMemorySaver())

    def test_offline_server_graph_pause_and_all_decisions_async(self):
        studio = importlib.import_module('research_assistant.studio')

        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                for action in ('approve', 'edit', 'cancel'):
                    graph = studio.create_graph(output_dir=directory)
                    self.assertIsNone(graph.checkpointer)
                    # Emulate the checkpointer injected by Agent Server.
                    graph.checkpointer = InMemorySaver()
                    config = {'configurable': {'thread_id': action}}
                    paused = await graph.ainvoke({'topic': '  LangGraph  '}, config)
                    self.assertEqual(paused['status'], 'planned')
                    self.assertEqual(paused['normalized_topic'], 'LangGraph')
                    self.assertEqual(paused['__interrupt__'][0].value['kind'], 'review_plan')
                    snapshot = await graph.aget_state(config)
                    self.assertEqual(snapshot.next, ('review_plan',))
                    decision = {'action': action}
                    if action == 'edit':
                        decision['plan'] = {'title': 'Исправленный план', 'sections': [
                            {'title': 'Новый раздел', 'questions': ['Как проверить State?']}]}
                    final = await graph.ainvoke(Command(resume=decision), config)
                    self.assertEqual(final['status'], 'cancelled' if action == 'cancel' else 'completed')
                    if action == 'cancel':
                        self.assertNotIn('sources', final)
                        self.assertNotIn('report_path', final)
                    else:
                        self.assertTrue(Path(final['report_path']).resolve().is_relative_to(Path(directory).resolve()))
                        self.assertIn('DEMO', Path(final['report_path']).read_text(encoding='utf-8'))
                        if action == 'edit':
                            self.assertEqual(final['plan'], decision['plan'])
                    self.assertFalse((await graph.aget_state(config)).next)

        with patch('research_assistant.planning.create_model', side_effect=AssertionError('Paid model')), \
             patch('research_assistant.graph.search_web', side_effect=AssertionError('Paid search')):
            asyncio.run(scenario())
