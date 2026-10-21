"""Two-process chat persistence fixture; all services are offline."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
from langchain_core.messages import AIMessage
from research_assistant.cli import main
from test_chat import FakeModel

mode, db = sys.argv[1:]
id_file = Path(db).with_suffix('.chat.txt')

class MemoryModel(FakeModel):
    def invoke(self, messages, config=None):
        if mode == 'continue':
            assert [m.content for m in messages[1:]] == ['Первый вопрос', 'Первый ответ', 'Второй вопрос']
        return super().invoke(messages)

model = MemoryModel([AIMessage('Первый ответ' if mode == 'create' else 'История восстановлена')])
with patch('research_assistant.chat.create_model', return_value=model), \
     patch('research_assistant.graph.generate_research_plan', side_effect=AssertionError('Research restarted')), \
     patch('research_assistant.graph.search_web', side_effect=AssertionError('Search restarted')), \
     patch('research_assistant.graph.generate_report_draft', side_effect=AssertionError('Report restarted')):
    from contextlib import redirect_stdout
    from io import StringIO
    out = StringIO()
    args = ['--discuss', 'research', '--question', 'Первый вопрос'] if mode == 'create' else [
        '--chat', id_file.read_text(encoding='utf-8'), '--question', 'Второй вопрос']
    with redirect_stdout(out):
        code = main(args + ['--checkpoint-db', db])
    if code == 0 and mode == 'create':
        id_file.write_text(json.loads(out.getvalue())['chat_thread_id'], encoding='utf-8')
    print(out.getvalue(), end='')
raise SystemExit(code)
