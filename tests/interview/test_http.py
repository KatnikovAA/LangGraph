"""Opt-in tests on real isolated Demo Agent Server and BFF."""
import os
import time
import unittest
from uuid import uuid4


@unittest.skipUnless(os.getenv('RA_INTERVIEW_HTTP_TESTS') == '1', 'Requires isolated Demo HTTP')
class InterviewHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import httpx
        cls.http = httpx.Client(base_url=os.getenv('RA_TEST_BASE_URL', 'http://127.0.0.1:8082'), timeout=40)
        if cls.http.get('/ready').json().get('mode') != 'demo':
            raise RuntimeError('Demo only')

    @classmethod
    def tearDownClass(cls):
        cls.http.close()

    def setUp(self):
        self.user = 'interview_' + uuid4().hex[:10]

    def api(self, action, body=None, **query):
        args = dict(params={'user_id': self.user, **query})
        response = self.http.post('/api/' + action, json=body, **args) if body is not None else self.http.get('/api/' + action, **args)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def wait(self, run, allow_error=False):
        for _ in range(300):
            data = self.api('run', **run)
            if data['status'] not in ('pending', 'running'):
                if not allow_error:
                    self.assertEqual(data['status'], 'success', data)
                return self.api('state', thread_id=run['thread_id'])
            time.sleep(.1)
        self.fail('Run timeout')

    def test_interview_report_chat_recovery_owner(self):
        payload = {'topic': 'Надёжность LangGraph', 'clarification': 'Восстановление'}
        request_id = uuid4().hex
        run = self.api('create_interview', {'request_id': request_id, **payload})
        recovered = self.api('recover', {'request_id': request_id, 'operation': 'create_interview', 'payload': payload})
        self.assertEqual(recovered['run_id'], run['run_id'])
        state = self.wait(run, allow_error=True)
        if state['error']:
            state = self.wait(self.api('resume', {'request_id': uuid4().hex, 'thread_id': run['thread_id']}))
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(len(state['interview']['transcript']), 2)
        self.assertEqual(self.api('create_interview', {'request_id': request_id, **payload}), run)
        self.assertEqual(self.api('state', thread_id=run['thread_id'])['checkpoint_id'], state['checkpoint_id'])
        report = self.http.get('/report', params={'user_id': self.user, 'thread_id': run['thread_id'], 'checkpoint_id': state['checkpoint_id']})
        self.assertEqual(report.status_code, 200)
        self.assertIn('Demo', report.text)
        chat = self.api('create_chat', {'request_id': uuid4().hex, 'research_thread_id': run['thread_id'],
            'research_checkpoint_id': state['checkpoint_id'], 'question': 'Объясни главное'})
        result = self.wait(chat)
        self.assertEqual(result['chat_settings']['research_checkpoint_id'], state['checkpoint_id'])
        self.assertEqual(result['chat_settings']['material_mode'], 'interview')
        forbidden = self.http.get('/api/state', params={'user_id': 'other', 'thread_id': run['thread_id']})
        self.assertEqual(forbidden.status_code, 403)

    def test_real_sse_running_and_round_identity(self):
        run = self.api('create_interview', {'request_id': uuid4().hex, 'topic': 'SSE'})
        import json
        records=[]
        kind=''
        with self.http.stream('GET', '/events', params={'user_id': self.user, **run}) as response:
            for line in response.iter_lines():
                if line.startswith('event: '):
                    kind=line[7:]
                if line.startswith('data: ') and kind == 'interview-progress':
                    event=json.loads(line[6:]); records.append(event)
                    self.assertEqual(event['run_id'], run['run_id'])
                    if event['node']=='ask_question' and event['status']=='running':
                        live=self.api('run', **run)
                        self.assertEqual(live['status'], 'running')
        self.assertTrue(any(e['status']=='done' for e in records))
        questions=[e for e in records if e['node']=='ask_question' and e['status']=='running']
        self.assertEqual([e['round'] for e in questions], [1,2])
        self.assertNotEqual(questions[0]['execution_id'], questions[1]['execution_id'])
        completed=self.wait(run)
        replay=self.http.get('/events',params={'user_id':self.user,**run})
        self.assertEqual(replay.status_code,200)
        self.assertEqual(self.api('state',thread_id=run['thread_id'])['checkpoint_id'],completed['checkpoint_id'])
        self.assertFalse(self.api('active-run',thread_id=run['thread_id'])['active'])

    def test_payload_and_unfinished_pin_rejected(self):
        response=self.http.post('/api/create_interview', params={'user_id':self.user}, json={
            'request_id':uuid4().hex,'topic':'x','output_dir':'elsewhere'})
        self.assertEqual(response.status_code,400)
        run=self.api('create_interview',{'request_id':uuid4().hex,'topic':'pending'})
        state=self.api('state',thread_id=run['thread_id'])
        if state['checkpoint_id'] and state['status']!='completed':
            response=self.http.post('/api/create_chat',params={'user_id':self.user},json={
                'request_id':uuid4().hex,'research_thread_id':run['thread_id'],
                'research_checkpoint_id':state['checkpoint_id'],'question':'x'})
            self.assertEqual(response.status_code,400)
