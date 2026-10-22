"""Opt-in tests against REAL Agent Server + BFF. No paid APIs, no mock server."""
import os
import time
import unittest
from uuid import uuid4


@unittest.skipUnless(os.getenv('RA_HTTP_TESTS') == '1', 'Запустите Demo серверы и задайте RA_HTTP_TESTS=1')
class WebHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import httpx
        cls.http = httpx.Client(base_url='http://127.0.0.1:8080', timeout=30)
        ready = cls.http.get('/ready').json()
        if ready.get('mode') != 'demo':
            raise RuntimeError('HTTP tests разрешены только в Demo.')

    @classmethod
    def tearDownClass(cls):
        cls.http.close()

    def setUp(self):
        self.user = 'test_' + uuid4().hex[:12]

    def api(self, action, body=None, **query):
        params = {'user_id': self.user, **query}
        response = self.http.post('/api/' + action, params=params, json=body) if body is not None else self.http.get('/api/' + action, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def wait(self, result):
        for _ in range(200):
            run = self.api('run', thread_id=result['thread_id'], run_id=result['run_id'])
            if run['status'] not in ('pending', 'running'):
                self.assertIn(run['status'], ('success', 'interrupted'), run)
                return self.api('state', thread_id=result['thread_id'])
            time.sleep(.1)
        self.fail('Run timeout')

    def research(self, approve=True):
        result = self.api('create_research', {'request_id': uuid4().hex, 'topic': '  Архитектура\tLangGraph\n '})
        state = self.wait(result)
        self.assertEqual(state['status'], 'planned')
        self.assertEqual(state['sources'], [])
        if approve:
            state = self.wait(self.api('review', {'request_id': uuid4().hex, 'thread_id': result['thread_id'], 'decision': {'action': 'approve'}}))
            self.assertEqual(state['status'], 'completed')
        return result['thread_id'], state

    def chat(self, thread, state, **kwargs):
        result = self.api('create_chat', {'request_id': uuid4().hex, 'research_thread_id': thread,
             'research_checkpoint_id': state['checkpoint_id'], 'question': 'Объясни главное', **kwargs})
        return result, self.wait(result)

    def test_review_report_chat_two_turns_and_idempotency(self):
        thread, state = self.research()
        self.assertIn('Demo', state['report_markdown'])
        response = self.http.get('/report', params={'user_id': self.user, 'thread_id': thread})
        self.assertEqual(response.status_code, 200)
        first, cs = self.chat(thread, state)
        self.assertEqual(cs['chat_settings']['research_checkpoint_id'], state['checkpoint_id'])
        body = {'request_id': uuid4().hex, 'thread_id': first['thread_id'], 'question': 'Поясни источник S1'}
        second = self.api('ask', body)
        self.assertEqual(self.api('ask', body), second)
        cs = self.wait(second)
        self.assertEqual(len([m for m in cs['messages'] if m['role'] == 'human']), 2)
        self.assertEqual(cs['status'], 'answered')

    def test_lost_response_recovery_reads_same_run(self):
        payload = {'topic': 'Lost response Demo'}
        request_id = uuid4().hex
        accepted = self.api('create_research', {'request_id': request_id, **payload})
        recovered = self.api('recover', {'request_id': request_id, 'operation': 'create_research', 'payload': payload})
        self.assertEqual(recovered['recovery'], 'found')
        self.assertEqual(recovered['run_id'], accepted['run_id'])
        self.assertEqual(recovered['thread_id'], accepted['thread_id'])
        self.wait(accepted)
        unknown = self.api('recover', {'request_id': uuid4().hex, 'operation': 'create_research', 'payload': payload})
        self.assertEqual(unknown['recovery'], 'not_received')

    def test_edit_cancel(self):
        thread, state = self.research(False)
        plan = state['plan']; plan['title'] = 'Изменённый план'
        edited = self.wait(self.api('review', {'request_id': uuid4().hex, 'thread_id': thread,
                                             'decision': {'action': 'edit', 'plan': plan}}))
        self.assertEqual(edited['plan']['title'], plan['title'])
        thread, _ = self.research(False)
        cancelled = self.wait(self.api('review', {'request_id': uuid4().hex, 'thread_id': thread, 'decision': {'action': 'cancel'}}))
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertEqual(cancelled['sources'], [])

    def test_memory_crud_shared_profile_and_isolation(self):
        self.api('memory', {'operation': 'profile', 'data': {'language': 'English'}})
        note = self.api('memory', {'operation': 'add', 'data': {'text': 'LangGraph предпочтение', 'topic': 'LangGraph'}})
        self.api('memory', {'operation': 'update', 'data': {'id': note['id'], 'patch': {'text': 'LangGraph изменён'}}})
        selected = self.api('memory', {'operation': 'retrieve', 'data': {'question': 'LangGraph'}})
        self.assertEqual(selected['notes'][0]['id'], note['id'])
        thread, state = self.research()
        first, cs = self.chat(thread, state)
        self.assertIn('connects', cs['messages'][-1]['text'])
        self.api('memory', {'operation': 'delete', 'data': {'id': note['id']}})
        self.assertEqual(self.api('memory')['notes'], [])
        for action in ('state', 'history'):
            response = self.http.get('/api/' + action, params={'user_id': 'other', 'thread_id': first['thread_id']})
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.http.get('/api/memory', params={'user_id': 'other'}).json()['profile']['language'], 'русский')

    def test_assistant_config_and_native_memory_tool(self):
        thread, state = self.research()
        brief_run, brief = self.chat(thread, state, assistant='brief')
        result, detailed = self.chat(thread, state, assistant='detailed')
        self.assertGreater(len(detailed['messages'][-1]['text']), len(brief['messages'][-1]['text']))
        switched = self.wait(self.api('ask', {'request_id': uuid4().hex, 'thread_id': brief_run['thread_id'],
                        'question': 'Объясни ещё', 'assistant': 'detailed'}))
        self.assertGreater(len(switched['messages'][-1]['text']), len(brief['messages'][-1]['text']))
        saved = self.wait(self.api('ask', {'request_id': uuid4().hex, 'thread_id': result['thread_id'], 'question': 'Запомни: LangGraph заметка'}))
        self.assertEqual(len(self.api('memory')['notes']), 1)
        self.assertEqual(saved['memory_selection']['operations'][0]['status'], 'saved')

    def test_history_fork_preserves_original_chat_pin(self):
        thread, original = self.research()
        chat, _ = self.chat(thread, original)
        points = self.api('history', thread_id=thread)
        point = next(p for p in points if p['next'] == ['review_plan'])
        self.api('branch', {'thread_id': thread, 'checkpoint_id': point['checkpoint_id'], 'operation': 'fork',
                           'plan': {'title': 'Альтернатива', 'sections': point['plan']['sections']}})
        branch = self.wait(self.api('resume', {'request_id': uuid4().hex, 'thread_id': thread}))
        self.assertEqual(branch['next'], ['review_plan'])
        completed = self.wait(self.api('review', {'request_id': uuid4().hex, 'thread_id': thread, 'decision': {'action': 'approve'}}))
        self.assertNotEqual(completed['report_markdown'], original['report_markdown'])
        pinned = self.api('state', thread_id=chat['thread_id'])
        self.assertEqual(pinned['chat_settings']['research_checkpoint_id'], original['checkpoint_id'])
        self.assertEqual(self.http.get('/report', params={'user_id': self.user, 'thread_id': thread, 'checkpoint_id': original['checkpoint_id']}).status_code, 200)

    def test_stream_before_completion_and_reconnect_does_not_repeat(self):
        thread, state = self.research()
        result = self.api('create_chat', {'request_id': uuid4().hex, 'research_thread_id': thread,
             'research_checkpoint_id': state['checkpoint_id'], 'question': 'Объясни', 'assistant': 'detailed'})
        with self.http.stream('GET', '/events', params={'user_id': self.user, **result}) as response:
            seen = []
            for line in response.iter_lines():
                seen.append(line)
                if line == 'event: token':
                    self.assertEqual(self.api('run', **result)['status'], 'running')
                    break
        self.assertIn('event: token', seen)
        state = self.wait(result)
        self.http.get('/events', params={'user_id': self.user, **result})
        state = self.api('state', thread_id=result['thread_id'])
        self.assertEqual(sum(m['role'] == 'human' for m in state['messages']), 1)

    def test_api_validation_paths_and_cross_origin(self):
        r = self.http.post('/api/create_research', params={'user_id': self.user}, json={'request_id': uuid4().hex, 'topic': 'x', 'output_dir': 'C:/Windows'})
        self.assertEqual(r.status_code, 400)
        r = self.http.post('/api/memory', params={'user_id': self.user}, json={'operation': 'reset'}, headers={'Origin': 'https://example.com'})
        self.assertEqual(r.status_code, 403)
        thread, state = self.research()
        r = self.http.post('/api/create_chat', params={'user_id': self.user}, json={
            'request_id': uuid4().hex, 'research_thread_id': thread,
            'research_checkpoint_id': None, 'question': 'Question'})
        self.assertEqual(r.status_code, 400)

    def test_long_chat_summary(self):
        thread, state = self.research()
        result, cs = self.chat(thread, state)
        for index in range(6):
            cs = self.wait(self.api('ask', {'request_id': uuid4().hex, 'thread_id': result['thread_id'],
                 'question': f'Вопрос {index}. ' + 'Объясни взаимодействие компонентов. ' * 90}))
        self.assertTrue(cs['summary_present'])
        self.assertEqual(sum(m['role'] == 'human' for m in cs['messages']), 7)

    def test_enqueue_after_failure_preserves_question_and_resume(self):
        thread, state = self.research()
        chat, _ = self.chat(thread, state)
        tid = chat['thread_id']
        first_question = '[demo:error-once] Сохрани незавершённый вопрос'
        first = self.api('ask', {'request_id': uuid4().hex, 'thread_id': tid, 'question': first_question})
        agent = self.http.get('/ready').json()['agent_url']
        raw_state = self.http.get(agent + f'/threads/{tid}/state').json()
        b = raw_state['values']['memory_binding']
        second = self.http.post(agent + f'/threads/{tid}/runs', json={
            'assistant_id': 'chat', 'input': {'incoming_question': 'Не должен заменить первый'},
            'context': {k: b[k] for k in ('user_id', 'thread_id', 'store_path')}, 'multitask_strategy': 'enqueue'})
        self.assertEqual(second.status_code, 200, second.text)
        for _ in range(200):
            r = self.api('run', thread_id=tid, run_id=second.json()['run_id'])
            if r['status'] not in ('pending', 'running'):
                break
            time.sleep(.1)
        self.assertEqual(r['status'], 'error')
        raw_state = self.http.get(agent + f'/threads/{tid}/state').json()
        self.assertEqual(raw_state['values']['question'], first_question)
        human = [m for m in raw_state['values']['messages'] if m['type'] == 'human']
        self.assertEqual(human[-1]['content'], first_question)
        resumed = self.wait(self.api('resume', {'request_id': uuid4().hex, 'thread_id': tid}))
        self.assertEqual(resumed['status'], 'answered')
        self.assertEqual(sum(m['role'] == 'human' for m in resumed['messages']), 2)
