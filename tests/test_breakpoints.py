import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from langgraph.types import Command
from research_assistant.graph import build_graph
from research_assistant.persistence import open_saver, workflow_settings
from research_assistant.history import stop_kind
from test_reporting import plan, hits, draft


class BreakpointTests(unittest.TestCase):
    def test_static_and_dynamic_resume_across_connections(self):
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            config = {'configurable': {'thread_id': 'a'}}
            search = Mock(return_value=hits())
            with open_saver(db) as saver:
                graph = build_graph(lambda t: plan(), review=True, search=True, report=True, output_dir=root,
                    checkpointer=saver, search_function=search, report_generator=lambda *a: draft(), break_before_search=True)
                graph.invoke({'topic': 'T', 'workflow': workflow_settings(db, root, 'a', break_before_search=True)}, config)
                self.assertEqual(stop_kind(graph.get_state(config)), 'dynamic_interrupt')
                graph.invoke(None, config)
                self.assertEqual(stop_kind(graph.get_state(config)), 'dynamic_interrupt')
                graph.invoke(Command(resume={'action': 'approve'}), config)
                self.assertEqual(stop_kind(graph.get_state(config)), 'static_breakpoint')
                search.assert_not_called()
            with open_saver(db) as saver:
                graph = build_graph(Mock(side_effect=AssertionError('Plan repeated')), review=True, search=True,
                    report=True, output_dir=root, checkpointer=saver, search_function=search,
                    report_generator=lambda *a: draft(), break_before_search=True)
                result = graph.invoke(None, config)
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(len(result['search_batches']), 1)
                search.assert_called_once()
