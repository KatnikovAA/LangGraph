import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch, Mock

from langchain_core.messages import AIMessage
from research_assistant.cli import main
from research_assistant.persistence import open_saver
from research_assistant.graph import build_graph
from research_assistant.chat import build_chat_graph
from test_chat import FakeModel
from test_chat_session import completed_research
from test_reporting import hits, draft


def cli(args):
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class CheckpointCliTests(unittest.TestCase):
    def test_inspection_branch_preparation_and_chat_binding(self):
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            original = completed_research(db, root)
            flags = ['--checkpoint-db', db]
            with patch('research_assistant.chat.create_model', return_value=FakeModel([AIMessage('A')])):
                code, out, err = cli(['--discuss', 'research', '--question', 'Q'] + flags)
            self.assertEqual(code, 0, err)
            chat = json.loads(out)['chat_thread_id']
            with open_saver(db) as saver:
                cg = build_chat_graph(checkpointer=saver)
                original_cp = cg.get_state({'configurable': {'thread_id': chat}}).values['chat_settings']['research_checkpoint_id']
            forbidden = Mock(side_effect=AssertionError('External API/write'))
            with patch('research_assistant.graph.generate_research_plan', forbidden), \
                 patch('research_assistant.graph.search_web', forbidden), \
                 patch('research_assistant.graph.generate_report_draft', forbidden), \
                 patch('research_assistant.graph.write_report', forbidden):
                code, out, err = cli(['--history', 'research'] + flags)
                self.assertEqual(code, 0, err)
                history = json.loads(out)['checkpoints']
                point = next(s for s in history if s['next'] == ['review_plan'])
                cp = point['checkpoint_id']
                code, out, err = cli(['--inspect', 'research', '--checkpoint-id', cp] + flags)
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)['checkpoint_id'], cp)
                self.assertNotIn('report_markdown', out)
                for mode, tid, checkpoint in [('inspect', 'research', 'missing'), ('inspect', 'missing', cp),
                                             ('inspect', chat, cp), ('replay', 'research', original_cp)]:
                    code, out, err = cli(['--' + mode, tid, '--checkpoint-id', checkpoint] + flags)
                    self.assertEqual(code, 2, err)
                    self.assertEqual(out, '')
                code, out, err = cli(['--history', chat] + flags)
                self.assertEqual(code, 2)
                self.assertIn('Chat Thread', err)
                plan_file = Path(root) / 'plan.json'
                plan_file.write_text(json.dumps({'title': 'B', 'sections': [
                    {'title': 'Alternative B', 'questions': ['New question?']}]}), encoding='utf-8')
                code, out, err = cli(['--fork', 'research', '--checkpoint-id', cp, '--plan-file', str(plan_file)] + flags)
                self.assertEqual(code, 0, err)
                branch_cp = json.loads(out)['checkpoint_id']
                self.assertNotEqual(branch_cp, cp)
                forbidden.assert_not_called()
            # Original Chat still works while latest Research is an unfinished alternative.
            with patch('research_assistant.chat.create_model', return_value=FakeModel([AIMessage('Original report answer')])):
                code, out, err = cli(['--chat', chat, '--question', 'Q2'] + flags)
            self.assertEqual(code, 0, err)
            queries = []
            with patch('research_assistant.graph.generate_research_plan', side_effect=AssertionError('Plan repeated')), \
                 patch('research_assistant.graph.search_web', side_effect=lambda q: queries.append(q) or hits()), \
                 patch('research_assistant.graph.generate_report_draft', return_value=draft()), \
                 patch('research_assistant.cli.require_terminal'), \
                 patch('research_assistant.cli.request_review', return_value={'action': 'approve'}) as review:
                with patch('research_assistant.reporting.os.replace', side_effect=PermissionError('offline write failure')):
                    code, out, err = cli(['--resume', 'research', '--checkpoint-id', branch_cp] + flags)
                self.assertEqual(code, 2, err)
                self.assertEqual(out, '')
                with open_saver(db) as saver:
                    state = build_graph(review=True, search=True, report=True, checkpointer=saver).get_state(
                        {'configurable': {'thread_id': 'research'}})
                    artifact = state.values['workflow']['artifact_id']
                    failed_cp = state.config['configurable']['checkpoint_id']
                call_count = len(queries)
                code, out, err = cli(['--resume', 'research', '--checkpoint-id', failed_cp] + flags)
                self.assertEqual(code, 0, err)
                result = json.loads(out)
                self.assertEqual(len(queries), call_count)
                self.assertEqual(result['workflow']['artifact_id'], artifact)
                review.assert_called_once()
                self.assertIn('Alternative B', queries[0])
                self.assertNotEqual(result['report_path'], original['report_path'])
                completed_cp = result['checkpoint_id']
                code, out, err = cli(['--resume', 'research'] + flags)
                self.assertEqual(json.loads(out)['report_path'], result['report_path'])
                code, out, err = cli(['--resume', 'research', '--checkpoint-id', original_cp] + flags)
                self.assertEqual(json.loads(out)['checkpoint_id'], original_cp)
                self.assertEqual(json.loads(out)['report_path'], original['report_path'])
            for checkpoint in (original_cp, completed_cp):
                with patch('research_assistant.chat.create_model', return_value=FakeModel([AIMessage('Chosen report')])):
                    code, out, err = cli(['--discuss', 'research', '--research-checkpoint-id', checkpoint,
                                          '--question', 'Q'] + flags)
                self.assertEqual(code, 0, err)
                new_chat = json.loads(out)['chat_thread_id']
                with open_saver(db) as saver:
                    state = build_chat_graph(checkpointer=saver).get_state({'configurable': {'thread_id': new_chat}}).values
                    self.assertEqual(state['chat_settings']['research_checkpoint_id'], checkpoint)

    def test_static_breakpoint_resume_in_fresh_processes(self):
        with tempfile.TemporaryDirectory() as root:
            worker = str(Path(__file__).with_name('breakpoint_worker.py'))
            def run(mode):
                process = subprocess.run([sys.executable, worker, mode, root], capture_output=True,
                                         text=True, encoding='utf-8', timeout=30)
                self.assertEqual(process.returncode, 0, process.stderr)
                return json.loads(process.stdout)
            self.assertEqual(run('create')['stop_kind'], 'dynamic_interrupt')
            self.assertEqual(run('approve')['stop_kind'], 'static_breakpoint')
            self.assertEqual(run('continue')['status'], 'completed')

    def test_invalid_flags_and_plan_leave_history_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            completed_research(db, root)
            code, out, err = cli(['--history', 'research', '--checkpoint-db', db])
            history = json.loads(out)['checkpoints']
            cp = next(s['checkpoint_id'] for s in history if s['next'] == ['review_plan'])
            file = Path(root) / 'bad.json'
            file.write_text('{}', encoding='utf-8')
            cases = [['--fork', 'research', '--checkpoint-id', cp, '--plan-file', str(file)],
                     ['--history', 'research', '--question', 'Q'], ['--inspect', 'research'],
                     ['--replay', 'research', '--checkpoint-id', cp, '--plan-file', str(file)],
                     ['--resume', 'research', '--checkpoint-id', ''], ['--break-before-search', '--topic', 'Q']]
            for args in cases:
                code, out, err = cli(args + ['--checkpoint-db', db])
                self.assertEqual(code, 2, err)
                self.assertEqual(out, '')
            code, out, err = cli(['--history', 'research', '--checkpoint-db', db])
            self.assertEqual(len(json.loads(out)['checkpoints']), len(history))
