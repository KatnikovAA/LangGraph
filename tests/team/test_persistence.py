import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PersistenceTests(unittest.TestCase):
    def test_new_process_resume_preserves_successful_a_and_b_steps(self):
        script=Path(__file__).with_name('persistence_worker.py')
        env={**os.environ,'PYTHONPATH':str(script.parents[2]),'PYTHONUTF8':'1'}
        with tempfile.TemporaryDirectory() as root:
            first=subprocess.run([sys.executable,str(script),root,'first'],env=env,capture_output=True,text=True,timeout=45)
            self.assertEqual(first.returncode,0,first.stdout+first.stderr)
            before=[json.loads(s) for s in (Path(root)/'calls.jsonl').read_text().splitlines()]
            self.assertFalse(any(c[0]=='report' for c in before))
            second=subprocess.run([sys.executable,str(script),root,'resume'],env=env,capture_output=True,text=True,timeout=45)
            self.assertEqual(second.returncode,0,second.stdout+second.stderr)
            after=[json.loads(s) for s in (Path(root)/'calls.jsonl').read_text().splitlines()]
            extra=after[len(before):]
            self.assertEqual([c[0] for c in extra],['expert','synthesis','report'])
            self.assertEqual(extra[0],['expert','B'])
            result=json.loads((Path(root)/'final.json').read_text(encoding='utf-8'))
            self.assertEqual([len(r['transcript']) for r in result['worker_results']],[2,2])
