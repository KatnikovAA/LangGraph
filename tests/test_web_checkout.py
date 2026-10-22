"""Opt-in: clean source copy without .env or databases, real independent servers."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from uuid import uuid4


@unittest.skipUnless(os.getenv('RA_CHECKOUT_TESTS') == '1', 'Проверка чистой копии: RA_CHECKOUT_TESTS=1 и web extra')
class CheckoutTests(unittest.TestCase):
    def test_clean_source_demo_end_to_end(self):
        import httpx
        root = Path(__file__).resolve().parents[1]
        def port():
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0)); return probe.getsockname()[1]
        with tempfile.TemporaryDirectory(prefix='ra-checkout-') as temp:
            checkout = Path(temp)
            shutil.copytree(root/'research_assistant', checkout/'research_assistant', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copy2(root/'langgraph.web.json', checkout/'langgraph.web.json')
            self.assertFalse((checkout/'.env').exists())
            agent_port, web_port = port(), port()
            env = {**os.environ, 'RA_WEB_MODE': 'demo', 'RA_WEB_DATA': str(checkout/'data'),
                   'RA_AGENT_URL': f'http://127.0.0.1:{agent_port}', 'RA_WEB_PORT': str(web_port), 'PYTHONUTF8': '1'}
            log = (checkout/'process.log').open('w', encoding='utf-8')
            processes = []
            try:
                for module in ('research_assistant.web.agent', 'research_assistant.web'):
                    processes.append(subprocess.Popen([sys.executable, '-m', module], cwd=checkout,
                                                     env=env, stdout=log, stderr=log))
                with httpx.Client(base_url=f'http://127.0.0.1:{web_port}', timeout=3) as client:
                    for _ in range(200):
                        if any(p.poll() is not None for p in processes):
                            self.fail('Процесс чистой копии завершился: ' + (checkout/'process.log').read_text(encoding='utf-8')[-1200:])
                        try:
                            if client.get('/ready').status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(.1)
                    else:
                        self.fail('Чистая копия не запустилась: ' + (checkout/'process.log').read_text(encoding='utf-8')[-1200:])
                    self.assertIn('Research Assistant', client.get('/').text)
                    def api(action, data=None, **query):
                        response = client.post('/api/'+action, params={'user_id': 'clean', **query}, json=data) if data is not None else client.get('/api/'+action, params={'user_id': 'clean', **query})
                        self.assertEqual(response.status_code, 200, response.text)
                        return response.json()
                    def wait(run):
                        for _ in range(200):
                            result = api('run', thread_id=run['thread_id'], run_id=run['run_id'])
                            if result['status'] not in ('pending', 'running'):
                                self.assertIn(result['status'], ('success', 'interrupted'))
                                return api('state', thread_id=run['thread_id'])
                            time.sleep(.1)
                        self.fail('Run timeout')
                    run = api('create_research', {'request_id': uuid4().hex, 'topic': 'Чистый запуск'})
                    self.assertEqual(wait(run)['status'], 'planned')
                    report = wait(api('review', {'request_id': uuid4().hex, 'thread_id': run['thread_id'], 'decision': {'action': 'approve'}}))
                    self.assertEqual(report['status'], 'completed')
                    chat = wait(api('create_chat', {'request_id': uuid4().hex, 'research_thread_id': run['thread_id'],
                        'research_checkpoint_id': report['checkpoint_id'], 'question': 'Запомни: чистый запуск'}))
                    self.assertEqual(chat['status'], 'answered')
                    self.assertEqual(len(api('memory')['notes']), 1)
                    runtime = checkout/'data'/'runtime'/'langgraph.json'
                    self.assertIn(checkout.as_posix(), runtime.read_text())
            finally:
                (checkout/'data').mkdir(exist_ok=True)
                for name in ('bff.stop', 'agent.stop'):
                    (checkout/'data'/name).touch()
                for process in processes:
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        process.terminate(); process.wait(timeout=10)
                log.close()
            live_env = {**env, 'RA_WEB_MODE': 'live', 'RA_WEB_DATA': str(checkout/'live'),
                        'POLZA_API_KEY': '', 'POLZA_MODEL': '', 'TAVILY_API_KEY': ''}
            rejected = subprocess.run([sys.executable, '-m', 'research_assistant.web.agent'], cwd=checkout,
                                      env=live_env, capture_output=True, timeout=20)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse((checkout/'live'/'memory.sqlite').exists())
            self.assertFalse((checkout/'live'/'runtime'/'.langgraph_api').exists())
