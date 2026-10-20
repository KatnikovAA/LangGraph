import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from research_assistant.cli import main
from research_assistant.persistence import open_saver
from research_assistant.graph import build_graph
from research_assistant.planning import PlanGenerationError
from research_assistant.reporting import ReportError, write_report
from test_reporting import plan, hits, draft


class ReportCliTests(unittest.TestCase):
    def run_cli(self, argv, *, interactive=False, decision=None):
        out, err = StringIO(), StringIO()
        stdin = Mock()
        stdin.isatty.return_value = interactive
        with patch('sys.stdin', stdin), patch('research_assistant.cli.request_review',
                                               return_value=decision or {'action': 'approve'}) as review:
            with redirect_stdout(out), redirect_stderr(err):
                code = main(argv)
        return code, out.getvalue(), err.getvalue(), review

    def test_bad_flags_rejected_before_any_api(self):
        for flags in [ ['--topic', 'Тема', '--report'], ['--topic', 'Тема', '--review', '--report'],
                      ['--topic', 'Тема', '--pause-after-plan'], ['--topic', 'Тема', '--output-dir', 'x'],
                      ['--resume', 'id', '--topic', 'Тема'], ['--resume', 'id', '--review'],
                      ['--resume', 'id', '--search'], ['--resume', 'id', '--report'],
                      ['--resume', 'id', '--output-dir', 'x'], ['--resume', 'id', '--pause-after-plan']]:
            with self.subTest(flags=flags), patch('research_assistant.cli.build_graph') as builder:
                code, out, err, _ = self.run_cli(flags)
                self.assertEqual(code, 2)
                self.assertEqual(out, '')
                self.assertIn('Ошибка', err)
                builder.assert_not_called()

    def test_unknown_thread_and_missing_db_no_services(self):
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            for existing in [False, True]:
                if existing:
                    with open_saver(db) as saver:
                        saver.setup()
                with patch('research_assistant.graph.generate_research_plan') as generator, \
                     patch('research_assistant.graph.search_web') as searcher, \
                     patch('research_assistant.graph.generate_report_draft') as reporter:
                    code, out, err, _ = self.run_cli(['--resume', 'unknown', '--checkpoint-db', db])
                    self.assertEqual(code, 2)
                    self.assertEqual(out, '')
                    self.assertIn('не найден', err.lower().replace('не найдена', 'не найден'))
                    generator.assert_not_called()
                    searcher.assert_not_called()
                    reporter.assert_not_called()

    def test_full_pause_cancel_no_sources_and_completed_resume(self):
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            flags = ['--topic', 'Тема', '--review', '--search', '--report', '--checkpoint-db', db,
                     '--output-dir', str(Path(root) / 'out')]
            with patch('research_assistant.graph.generate_research_plan', return_value=plan()) as planner, \
                 patch('research_assistant.graph.search_web', return_value=[]) as searcher, \
                 patch('research_assistant.graph.generate_report_draft', return_value=draft()) as reporter:
                code, out, err, review = self.run_cli(flags + ['--pause-after-plan'])
                self.assertEqual(code, 0, err)
                paused = json.loads(out)
                self.assertEqual(paused['status'], 'planned')
                review.assert_not_called()
                thread_id = paused['thread_id']
                resume = ['--resume', thread_id, '--checkpoint-db', db]
                code, out, err, review = self.run_cli(resume)
                self.assertEqual(code, 2)
                self.assertIn('терминал', err)
                code, out, err, review = self.run_cli(resume, interactive=True, decision={'action': 'cancel'})
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)['status'], 'cancelled')
                searcher.assert_not_called()
                code, out, err, review = self.run_cli(resume)
                self.assertEqual(code, 0, err)
                review.assert_not_called()
                code, out, err, _ = self.run_cli(flags, interactive=True)
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)['status'], 'no_sources')
                reporter.assert_not_called()
                self.assertFalse((Path(root) / 'out').exists())
                self.assertEqual(planner.call_count, 2)

    def test_generation_and_write_errors_return_no_json_then_resume(self):
        for fail_at in ['generate_report', 'save_report', 'generate_plan']:
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as root:
                db, output = str(Path(root) / 'db.sqlite'), str(Path(root) / 'out')
                flags = ['--topic', 'Тема', '--review', '--search', '--report', '--checkpoint-db', db, '--output-dir', output]
                with patch('research_assistant.graph.generate_research_plan', return_value=plan()) as planner, \
                     patch('research_assistant.graph.search_web', return_value=hits()) as searcher, \
                     patch('research_assistant.graph.generate_report_draft', return_value=draft()) as reporter, \
                     patch('research_assistant.graph.write_report', wraps=write_report) as writer:
                    failing = {'generate_report': reporter, 'save_report': writer, 'generate_plan': planner}[fail_at]
                    failing.side_effect = PlanGenerationError('Ошибка плана') if fail_at == 'generate_plan' else ReportError('Ошибка Report')
                    code, out, err, _ = self.run_cli(flags, interactive=True)
                    self.assertEqual(code, 2)
                    self.assertEqual(out, '')
                    thread_id = err.split('Thread: ')[1].splitlines()[0]
                    self.assertFalse(Path(output).exists())
                    failing.side_effect = None
                    code, out, err, _ = self.run_cli(['--resume', thread_id, '--checkpoint-db', db], interactive=True)
                    self.assertEqual(code, 0, err)
                    self.assertEqual(json.loads(out)['status'], 'completed')
                    self.assertEqual(planner.call_count, 2 if fail_at == 'generate_plan' else 1)
                    self.assertEqual(reporter.call_count, 2 if fail_at == 'generate_report' else 1)
                    self.assertEqual(searcher.call_count, 1)
