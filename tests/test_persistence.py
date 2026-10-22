import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from langgraph.types import Command

from research_assistant.graph import build_graph
from research_assistant.reporting import ReportError
from test_reporting import draft, hits, plan


class PersistenceTests(unittest.TestCase):
    def test_file_failure_resume_skips_completed_nodes_and_completed_resume_is_read_only(self):
        from research_assistant.persistence import open_saver, workflow_settings, inspect_thread
        with tempfile.TemporaryDirectory() as root:
            db, output = str(Path(root) / 'db.sqlite'), str(Path(root) / 'out')
            config = {'configurable': {'thread_id': 'a'}}
            planner, searcher, reporter = Mock(return_value=plan()), Mock(return_value=hits()), Mock(return_value=draft())
            with open_saver(db) as saver:
                graph = build_graph(planner, review=True, search=True, report=True, output_dir=output,
                                    checkpointer=saver, search_function=searcher, report_generator=reporter)
                graph.invoke({'topic': 'Кириллица', 'workflow': workflow_settings(db, output, 'a')}, config, durability='sync')
                with patch('research_assistant.reporting.os.replace', side_effect=PermissionError()):
                    with self.assertRaises(ReportError):
                        graph.invoke(Command(resume={'action': 'approve'}), config, durability='sync')
                self.assertEqual(graph.get_state(config).values['status'], 'report_ready')
                self.assertEqual(graph.get_state(config).next, ('save_report',))
            with open_saver(db) as saver:
                forbidden = Mock(side_effect=AssertionError('API repeated'))
                graph = build_graph(forbidden, review=True, search=True, report=True, output_dir=output,
                                    checkpointer=saver, search_function=forbidden, report_generator=forbidden)
                snapshot = inspect_thread(graph, config, db)
                self.assertEqual(Path(snapshot.values['workflow']['output_dir']).resolve(), Path(output).resolve())
                result = graph.invoke(None, config, durability='sync')
                self.assertEqual(result['status'], 'completed')
                self.assertIn('Обзор', Path(result['report_path']).read_text(encoding='utf-8'))
                self.assertFalse(inspect_thread(graph, config, db).next)
                forbidden.assert_not_called()
                self.assertEqual(len(list(Path(output).glob('*.md'))), 1)
            planner.assert_called_once()
            reporter.assert_called_once()
            searcher.assert_called_once()

    def test_unknown_incompatible_and_secret_free_checkpoints(self):
        from research_assistant.persistence import open_saver, workflow_settings, inspect_thread, PersistenceError
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            config = {'configurable': {'thread_id': 'a'}}
            with open_saver(db) as saver:
                graph = build_graph(lambda t: plan(), review=True, search=True, report=True, checkpointer=saver)
                with self.assertRaisesRegex(PersistenceError, 'не найден'):
                    inspect_thread(graph, config, db)
                settings = workflow_settings(db, root, 'a')
                with patch.dict(os.environ, {'POLZA_API_KEY': 'secret-marker-123', 'TAVILY_API_KEY': 'search-secret-456'}):
                    graph.invoke({'topic': 'Тема', 'workflow': settings}, config, durability='sync')
                for snapshot in graph.get_state_history(config):
                    self.assertNotIn('secret-marker-123', repr(snapshot))
                    self.assertNotIn('search-secret-456', repr(snapshot))
                for field, value in [('version', 999), ('mode', 'other'), ('output_dir', 'relative')]:
                    graph.update_state(config, {'workflow': {**settings, field: value}})
                    with self.assertRaises(PersistenceError):
                        inspect_thread(graph, config, db)
            self.assertNotIn(b'secret-marker-123', Path(db).read_bytes())

    def test_two_real_processes_and_completed_cli_resume(self):
        with tempfile.TemporaryDirectory() as root:
            db, output = str(Path(root) / 'db.sqlite'), str(Path(root) / 'out')
            worker = Path(__file__).with_name('persistence_worker.py')
            def run(mode):
                result = subprocess.run([sys.executable, str(worker), mode, db, output], capture_output=True,
                                        text=True, encoding='utf-8', timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            paused = run('pause')
            self.assertEqual(paused['status'], 'planned')
            self.assertTrue(paused['paused'])
            self.assertNotIn('__interrupt__', paused)
            completed = run('resume')
            self.assertEqual(completed['status'], 'completed')
            self.assertTrue(Path(completed['report_path']).is_file())
            self.assertEqual(run('completed'), completed)

    def test_two_threads_have_separate_states_and_files(self):
        from research_assistant.persistence import open_saver, workflow_settings
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            with open_saver(db) as saver:
                graph = build_graph(lambda t: plan(), review=True, search=True, report=True,
                                    output_dir=root, checkpointer=saver, search_function=lambda q: hits(),
                                    report_generator=lambda *args: draft())
                results = []
                for key in ['one', 'two']:
                    config = {'configurable': {'thread_id': key}}
                    graph.invoke({'topic': key, 'workflow': workflow_settings(db, root, key)}, config, durability='sync')
                    results.append(graph.invoke(Command(resume={'action': 'approve'}), config, durability='sync'))
                self.assertNotEqual(results[0]['report_path'], results[1]['report_path'])
                self.assertEqual([r['topic'] for r in results], ['one', 'two'])
