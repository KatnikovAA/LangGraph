import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from langgraph.types import Command
from research_assistant.graph import build_graph
from research_assistant.persistence import open_saver, workflow_settings, PersistenceError
from research_assistant.time_travel import prepare_branch
from research_assistant.history import research_checkpoint
from test_reporting import plan, hits, draft


class TimeTravelTests(unittest.TestCase):
    def test_fork_replay_review_files_and_original_checkpoint(self):
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            with open_saver(db) as saver:
                planner, search = Mock(return_value=plan()), Mock(return_value=hits())
                graph = build_graph(planner, review=True, search=True, report=True, output_dir=root,
                    checkpointer=saver, search_function=search, report_generator=lambda *a: draft())
                config = {'configurable': {'thread_id': 'a'}}
                graph.invoke({'topic': 'T', 'workflow': workflow_settings(db, root, 'a')}, config)
                point = next(s for s in graph.get_state_history(config) if s.next == ('review_plan',))
                cp = point.config['configurable']['checkpoint_id']
                original = graph.invoke(Command(resume={'action': 'approve'}), config)
                original_text = Path(original['report_path']).read_bytes()
                alternative = {**plan(), 'title': 'Alternative B'}
                paths = [original['report_path']]
                for operation in ('fork', 'replay'):
                    calls = search.call_count
                    branch_config = prepare_branch(graph, 'a', cp, db, operation=operation,
                                                   new_plan=alternative if operation == 'fork' else None)
                    self.assertEqual(search.call_count, calls)
                    branch = graph.get_state(branch_config)
                    self.assertEqual(branch.next, ('review_plan',))
                    self.assertEqual(branch.parent_config['configurable']['checkpoint_id'], cp)
                    self.assertEqual(branch.values['search_batches'], [])
                    graph.invoke(None, branch_config)
                    paused = graph.get_state(config)
                    self.assertTrue(any(t.interrupts for t in paused.tasks))
                    self.assertEqual(paused.values['plan']['title'], alternative['title'] if operation == 'fork' else plan()['title'])
                    result = graph.invoke(Command(resume={'action': 'approve'}), paused.config)
                    paths.append(result['report_path'])
                    self.assertEqual(len(result['search_batches']), 1)
                    self.assertEqual(len(result['sources']), len(original['sources']))
                    self.assertEqual(graph.invoke(None, graph.get_state(config).config)['report_path'], result['report_path'])
                self.assertEqual(len(set(paths)), 3)
                self.assertEqual(Path(original['report_path']).read_bytes(), original_text)
                self.assertEqual(research_checkpoint(graph, 'a', cp, db).values['plan'], point.values['plan'])
                planner.assert_called_once()
                before = len(list(graph.get_state_history(config)))
                with self.assertRaises(PersistenceError):
                    prepare_branch(graph, 'a', cp, db, operation='fork', new_plan={})
                with self.assertRaises(PersistenceError):
                    prepare_branch(graph, 'a', graph.get_state(config).config['configurable']['checkpoint_id'], db, operation='replay')
                self.assertEqual(len(list(graph.get_state_history(config))), before)
