"""Offline three-process Static Breakpoint CLI fixture."""
import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
from research_assistant.cli import main
from test_reporting import plan, hits, draft
from contextlib import redirect_stdout
from io import StringIO

mode, root = sys.argv[1:]
db = str(Path(root) / 'db.sqlite')
id_file = Path(root) / 'thread.txt'
def forbidden(*args, **kwargs):
    raise AssertionError('Repeated service or unexpected Review')
with patch('research_assistant.graph.generate_research_plan', side_effect=lambda t: plan() if mode == 'create' else forbidden()), \
     patch('research_assistant.graph.search_web', side_effect=lambda q: hits() if mode == 'continue' else forbidden()), \
     patch('research_assistant.graph.generate_report_draft', side_effect=lambda *args: draft() if mode == 'continue' else forbidden()), \
     patch('research_assistant.cli.require_terminal'), \
     patch('research_assistant.cli.request_review', side_effect=lambda p: {'action': 'approve'} if mode == 'approve' else forbidden()):
    args = (['--topic', 'T', '--review', '--search', '--report', '--pause-after-plan', '--break-before-search',
             '--output-dir', root] if mode == 'create' else ['--resume', id_file.read_text(encoding='utf-8')])
    out = StringIO()
    with redirect_stdout(out):
        code = main(args + ['--checkpoint-db', db])
    if code == 0 and mode == 'create':
        id_file.write_text(json.loads(out.getvalue())['thread_id'], encoding='utf-8')
    print(out.getvalue(), end='')
raise SystemExit(code)
