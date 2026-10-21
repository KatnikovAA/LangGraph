import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from langgraph.types import Command
from research_assistant.graph import build_graph
from research_assistant.persistence import open_saver, workflow_settings, PersistenceError
from research_assistant.history import research_history, research_checkpoint, describe_snapshot
from test_reporting import plan, hits, draft


class HistoryTests(unittest.TestCase):
    def test_read_only_history_exact_checkpoint_and_wrong_thread(self):
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            with open_saver(db) as saver:
                graph = build_graph(lambda t: plan(), review=True, search=True, report=True, output_dir=root,
                                    checkpointer=saver, search_function=lambda q: hits(), report_generator=lambda *a: draft())
                for tid in ('a', 'b'):
                    graph.invoke({'topic': tid, 'workflow': workflow_settings(db, root, tid)}, {'configurable': {'thread_id': tid}})
                before = list(graph.get_state_history({'configurable': {'thread_id': 'a'}}))
                forbidden = Mock(side_effect=AssertionError('Execution'))
                graph.invoke = forbidden
                history = research_history(graph, 'a', db)
                cp = history[-1].config['configurable']['checkpoint_id']
                snapshot = research_checkpoint(graph, 'a', cp, db)
                self.assertEqual(describe_snapshot(snapshot)['checkpoint_id'], cp)
                for tid, checkpoint in [('a', 'unknown'), ('b', cp), ('unknown', cp)]:
                    with self.assertRaises(PersistenceError):
                        research_checkpoint(graph, tid, checkpoint, db)
                self.assertEqual(len(before), len(list(graph.get_state_history({'configurable': {'thread_id': 'a'}}))))
                forbidden.assert_not_called()
