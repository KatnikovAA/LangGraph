"""Explicit opt-in: orderly restart of the local Demo processes, preserving data."""
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest


@unittest.skipUnless(os.getenv('RA_RESTART_TESTS') == '1', 'Отдельная проверка перезапуска Demo: RA_RESTART_TESTS=1')
class RestartTests(unittest.TestCase):
    def test_threads_reports_profile_notes_and_assistants_survive(self):
        import httpx
        root = Path(__file__).resolve().parents[1]
        client = httpx.Client(base_url='http://127.0.0.1:8080', timeout=5)
        self.addCleanup(client.close)
        self.assertEqual(client.get('/ready').json()['mode'], 'demo')
        threads = client.get('/api/threads', params={'user_id': 'alice'}).json()
        before = {t['thread_id']: client.get('/api/state', params={'user_id': 'alice', 'thread_id': t['thread_id']}).json() for t in threads}
        self.assertTrue(before)
        memory = client.get('/api/memory', params={'user_id': 'alice'}).json()
        self.assertEqual(memory['profile']['language'], 'English')
        self.assertTrue(memory['notes'])
        assistants = client.get('/api/assistants', params={'user_id': 'alice'}).json()
        subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'RemoteSigned', '-File', str(root/'scripts/stop-web.ps1')], check=True, cwd=root)
        for _ in range(100):
            try:
                client.get('/health')
            except httpx.HTTPError:
                break
            time.sleep(.1)
        subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'RemoteSigned', '-File', str(root/'scripts/start-web.ps1'), '-Python', sys.executable], check=True, cwd=root, timeout=60)
        after = client.get('/api/threads', params={'user_id': 'alice'}).json()
        self.assertEqual({t['thread_id'] for t in threads}, {t['thread_id'] for t in after})
        for tid, state in before.items():
            result = client.get('/api/state', params={'user_id': 'alice', 'thread_id': tid}).json()
            self.assertEqual(result['checkpoint_id'], state['checkpoint_id'])
            self.assertEqual(result['messages'], state['messages'])
            if state['status'] == 'completed':
                self.assertEqual(client.get('/report', params={'user_id': 'alice', 'thread_id': tid}).status_code, 200)
        self.assertEqual(client.get('/api/memory', params={'user_id': 'alice'}).json(), memory)
        self.assertEqual(client.get('/api/assistants', params={'user_id': 'alice'}).json(), assistants)
        self.assertEqual(client.get('/api/memory', params={'user_id': 'restart_other'}).json()['notes'], [])
