import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from langchain_core.messages import AIMessage
from research_assistant.cli import main
from research_assistant.user_memory import open_memory_store
from test_chat import FakeModel
from test_chat_session import completed_research


def run(args):
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class MemoryCliTests(unittest.TestCase):
    def test_crud_without_model(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / 'memory.sqlite')
            base = ['--user-id', 'alice', '--memory-db', path]
            def command(op, extra=[]):
                code, out, err = run(['--memory-command', op] + base + extra)
                self.assertEqual(code, 0, err)
                return json.loads(out)['result']
            with patch('research_assistant.chat.create_model', side_effect=AssertionError('Model')):
                command('profile-update', ['--memory-json', '{"language":"English"}'])
                self.assertEqual(command('profile-show')['language'], 'English')
                note = command('note-add', ['--memory-json', '{"text":"LangGraph note"}'])
                identifier = note['id']
                self.assertEqual(command('note-show', ['--note-id', identifier])['text'], 'LangGraph note')
                command('note-update', ['--note-id', identifier, '--memory-json', '{"topic":"LangGraph"}'])
                self.assertEqual(len(command('note-list')), 1)
                self.assertEqual(command('retrieve', ['--memory-query', 'LangGraph'])['notes'][0]['id'], identifier)
                command('note-delete', ['--note-id', identifier])
                self.assertEqual(command('note-list'), [])
                self.assertEqual(command('profile-reset')['profile']['language'], 'русский')
                for flags in [['--memory-command', 'profile-show'], ['--memory-command', 'profile-show', '--topic', 'X'],
                              ['--memory-command', 'note-add', '--memory-json', '{}'], ['--memory-json', '{}'],
                              ['--user-id', 'langgraph', '--memory-command', 'profile-show']]:
                    code, out, err = run(flags + ['--memory-db', path])
                    self.assertEqual(code, 2, err)
                    self.assertEqual(out, '')

    def test_owner_store_path_and_legacy_chat(self):
        with tempfile.TemporaryDirectory() as root:
            db, memory = str(Path(root) / 'checkpoints.sqlite'), str(Path(root) / 'memory.sqlite')
            completed_research(db, root)
            flags = ['--checkpoint-db', db]
            with patch('research_assistant.chat.create_model', return_value=FakeModel([AIMessage('A')])):
                code, out, err = run(['--discuss', 'research', '--question', 'Q', '--user-id', 'alice', '--memory-db', memory] + flags)
            self.assertEqual(code, 0, err)
            chat = json.loads(out)['chat_thread_id']
            for extra in [[], ['--user-id', 'bob'], ['--user-id', 'alice', '--memory-db', str(Path(root) / 'wrong.sqlite')]]:
                with patch('research_assistant.chat.create_model', side_effect=AssertionError('Model')):
                    code, out, err = run(['--chat', chat, '--question', 'Q2'] + extra + flags)
                self.assertEqual(code, 2, err)
                self.assertEqual(out, '')
            Path(memory).unlink()
            with open_memory_store(memory):
                pass
            code, out, err = run(['--chat', chat, '--user-id', 'alice', '--question', 'Q2'] + flags)
            self.assertEqual(code, 2)
            self.assertIn('заменён', err)
            with patch('research_assistant.chat.create_model', return_value=FakeModel([AIMessage('Legacy')])):
                code, out, err = run(['--discuss', 'research', '--question', 'Q'] + flags)
            self.assertEqual(code, 0, err)
            legacy = json.loads(out)['chat_thread_id']
            code, out, err = run(['--chat', legacy, '--user-id', 'alice', '--question', 'Q2'] + flags)
            self.assertEqual(code, 2)
            self.assertIn('версии 3', err)

    def test_new_process_threads_share_only_their_user_memory(self):
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'checkpoints.sqlite')
            completed_research(db, root)
            worker = str(Path(__file__).with_name('memory_worker.py'))
            for mode in ('write', 'read', 'other'):
                process = subprocess.run([sys.executable, worker, mode, root], capture_output=True,
                                         text=True, encoding='utf-8', timeout=30)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(json.loads(process.stdout)['status'], 'answered')

    def test_streaming_keeps_store_contents_private(self):
        from test_chat_streaming import ChunkModel
        from research_assistant.user_memory import save_note
        with tempfile.TemporaryDirectory() as root:
            db, memory = str(Path(root) / 'checkpoints.sqlite'), str(Path(root) / 'memory.sqlite')
            completed_research(db, root)
            with open_memory_store(memory) as store:
                save_note(store, 'alice', {'text': 'LangGraph PRIVATE_NOTE_BODY'})
            with patch('research_assistant.chat.create_model', return_value=ChunkModel()):
                code, out, err = run(['--discuss', 'research', '--question', 'LangGraph', '--user-id', 'alice',
                                      '--memory-db', memory, '--checkpoint-db', db, '--stream'])
            self.assertEqual(code, 0, err)
            result = json.loads(out)
            self.assertEqual(result['answer'], 'Первая часть')
            self.assertEqual(len(result['memory_selection']['notes']), 1)
            self.assertNotIn('PRIVATE_NOTE_BODY', err)
            self.assertNotIn('PRIVATE_NOTE_BODY', out)

    def test_memory_chat_resume_after_write_in_new_process(self):
        with tempfile.TemporaryDirectory() as root:
            completed_research(str(Path(root) / 'checkpoints.sqlite'), root)
            worker = str(Path(__file__).with_name('memory_worker.py'))
            for mode, status in [('fail', 'failed_expected'), ('resume', 'answered')]:
                process = subprocess.run([sys.executable, worker, mode, root], capture_output=True,
                                         text=True, encoding='utf-8', timeout=30)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(json.loads(process.stdout)['status'], status)
