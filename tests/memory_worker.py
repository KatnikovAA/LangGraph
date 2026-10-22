"""Separate-process offline Profile write -> new Chat read -> other user isolation."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
from langchain_core.messages import AIMessage
from research_assistant.cli import main
from research_assistant.user_memory import MemoryError, open_memory_store, list_notes
from test_chat import FakeModel
from test_memory_agent import memory_call

mode, root = sys.argv[1:]
class MemoryModel(FakeModel):
    def invoke(self, messages, config=None):
        if mode == 'read':
            assert 'English' in messages[0].content
        elif mode == 'other':
            assert 'English' not in messages[0].content
        return super().invoke(messages, config)
responses = ([AIMessage('', tool_calls=[memory_call('update_profile', {'preferences': {'language': 'English'}})]),
              AIMessage('Saved')] if mode == 'write' else [AIMessage('Answer')])
if mode == 'fail':
    responses = [AIMessage('', tool_calls=[memory_call('save_note', {'note': {'text': 'LangGraph durable note'}})]),
                 MemoryError('Offline model failure after write')]
model = MemoryModel(responses)
with patch('research_assistant.chat.create_model', return_value=model):
    common = ['--user-id', 'bob' if mode == 'other' else 'alice', '--memory-db', str(Path(root) / 'memory.sqlite'),
              '--checkpoint-db', str(Path(root) / 'checkpoints.sqlite')]
    if mode == 'resume':
        args = ['--chat', (Path(root) / 'pending-chat.txt').read_text(encoding='utf-8')]
    else:
        question = 'Измени предпочтение: English' if mode == 'write' else 'Запомни LangGraph durable note' if mode == 'fail' else 'Question'
        args = ['--discuss', 'research', '--question', question]
    if mode == 'fail':
        from contextlib import redirect_stdout, redirect_stderr
        from io import StringIO
        import json
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(args + common)
        assert code == 2 and not out.getvalue(), err.getvalue()
        identifier = err.getvalue().split('Chat Thread: ')[1].splitlines()[0]
        (Path(root) / 'pending-chat.txt').write_text(identifier, encoding='utf-8')
        print(json.dumps({'status': 'failed_expected'}))
        code = 0
    else:
        code = main(args + common)
if mode in ('fail', 'resume'):
    with open_memory_store(str(Path(root) / 'memory.sqlite'), existing=True) as store:
        assert len(list_notes(store, 'alice')) == 1
raise SystemExit(code)
