"""Offline subprocess fixture: CLI + real SQLite; no external services."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_assistant.cli import main
from test_reporting import plan, hits, draft

mode, db, output = sys.argv[1:]
thread_file = Path(output).parent / 'thread.txt'

def forbidden(*args, **kwargs):
    raise AssertionError('Completed service was executed again')

with patch('research_assistant.graph.generate_research_plan', side_effect=(lambda t: plan()) if mode == 'pause' else forbidden), \
     patch('research_assistant.graph.search_web', side_effect=forbidden if mode in ('pause', 'completed') else lambda q: hits()), \
     patch('research_assistant.graph.generate_report_draft', side_effect=forbidden if mode in ('pause', 'completed') else lambda *args: draft()):
    if mode == 'pause':
        import json
        from contextlib import redirect_stdout
        from io import StringIO
        out = StringIO()
        with redirect_stdout(out):
            code = main(['--topic', 'Кириллица', '--review', '--search', '--report', '--pause-after-plan',
                         '--checkpoint-db', db, '--output-dir', output])
        if code == 0:
            thread_file.write_text(json.loads(out.getvalue())['thread_id'], encoding='utf-8')
        print(out.getvalue(), end='')
    else:
        with patch('research_assistant.cli.request_review', return_value={'action': 'approve'}), \
             patch('research_assistant.cli.require_terminal'):
            code = main(['--resume', thread_file.read_text(encoding='utf-8'), '--checkpoint-db', db])
raise SystemExit(code)
