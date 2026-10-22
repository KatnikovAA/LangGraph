import os
import time
import json
import unittest
from uuid import uuid4


@unittest.skipUnless(os.getenv('RA_TEAM_HTTP_TESTS')=='1','Requires isolated Team Demo HTTP')
class TeamHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import httpx
        cls.http=httpx.Client(base_url=os.getenv('RA_TEST_BASE_URL','http://127.0.0.1:8083'),timeout=45)
        if cls.http.get('/ready').json().get('mode')!='demo':raise RuntimeError('Demo only')
    @classmethod
    def tearDownClass(cls):cls.http.close()
    def setUp(self):self.user='team_'+uuid4().hex[:10]
    def api(self,action,body=None,**query):
        params={'user_id':self.user,**query}
        response=self.http.get('/api/'+action,params=params) if body is None else self.http.post('/api/'+action,params=params,json=body)
        self.assertEqual(response.status_code,200,response.text);return response.json()
    def wait(self,result):
        for _ in range(400):
            run=self.api('run',**result)
            if run['status'] not in ('pending','running'):return self.api('state',thread_id=result['thread_id'])
            time.sleep(.1)
        self.fail('Run timeout')
    def create(self):
        result=self.api('create_team',{'request_id':uuid4().hex,'topic':'HTTP Team','clarification':'Сравнить подходы'})
        state=self.wait(result)
        self.assertEqual(state['next'],['review_analysts']);self.assertEqual(state['team']['workers']['A']['questions'],[])
        return result,state
    def test_a_error_resume_and_chat(self):
        created,state=self.create();tid=created['thread_id']
        request_id=uuid4().hex
        roles=state['team']['roles'];roles[0]['focus']='Проверить практическую пользу'
        payload={'thread_id':tid,'decision':{'action':'edit','roles':roles}}
        run=self.api('review_team',{'request_id':request_id,**payload})
        self.assertEqual(self.api('review_team',{'request_id':request_id,**payload}),run)
        state=self.wait(run)
        if state['error']:
            self.assertEqual(state['team']['workers']['A']['status'],'completed')
            self.assertTrue(state['team']['workers']['B']['error'])
            self.assertEqual(len(state['team']['workers']['B']['answers']),1)
            state=self.wait(self.api('resume',{'request_id':uuid4().hex,'thread_id':tid}))
        self.assertEqual(state['status'],'completed')
        self.assertEqual([len(state['team']['workers'][k]['transcript']) for k in ['A','B']],[2,2])
        download=self.http.get('/report',params={'user_id':self.user,'thread_id':tid,'checkpoint_id':state['checkpoint_id']})
        self.assertEqual(download.status_code,200)
        chat=self.wait(self.api('create_chat',{'request_id':uuid4().hex,'research_thread_id':tid,
            'research_checkpoint_id':state['checkpoint_id'],'question':'Объясни обе позиции'}))
        self.assertEqual(chat['chat_settings']['research_checkpoint_id'],state['checkpoint_id'])
        self.assertEqual(chat['chat_settings']['material_mode'],'team')
        self.assertEqual(self.http.get('/api/state',params={'user_id':'other','thread_id':tid}).status_code,403)
    def test_cancel_recovery_and_payload(self):
        created,state=self.create();tid=created['thread_id']
        run=self.api('review_team',{'request_id':uuid4().hex,'thread_id':tid,'decision':{'action':'cancel'}})
        cancelled=self.wait(run);self.assertEqual(cancelled['status'],'cancelled')
        self.assertEqual(cancelled['sources'],[])
        invalid=self.http.post('/api/create_team',params={'user_id':self.user},json={'request_id':uuid4().hex,'topic':'x','roles':[]})
        self.assertEqual(invalid.status_code,400)
    def test_parallel_sse_and_reconnect(self):
        created,_=self.create();tid=created['thread_id']
        run=self.api('review_team',{'request_id':uuid4().hex,'thread_id':tid,'decision':{'action':'approve'}})
        events=[];kind='';simultaneous=False
        with self.http.stream('GET','/events',params={'user_id':self.user,**run}) as response:
            for line in response.iter_lines():
                if line.startswith('event: '):kind=line[7:]
                if line.startswith('data: ') and kind=='team-progress':
                    event=json.loads(line[6:]);events.append(event)
                    self.assertEqual(event['run_id'],run['run_id'])
                    if event['analyst_id'] in ('A','B') and event['status']=='running':
                        state=self.api('state',thread_id=tid)
                        workers=state['team']['workers']
                        simultaneous|=all(workers.get(k,{}).get('questions') for k in ('A','B'))
        self.assertTrue(simultaneous)
        for key in ('A','B'):
            self.assertEqual([e['round'] for e in events if e['analyst_id']==key and e['node']=='ask_question' and e['status']=='running'],[1,2])
        state=self.wait(run);checkpoint=state['checkpoint_id']
        self.http.get('/events',params={'user_id':self.user,**run}).raise_for_status()
        self.assertEqual(self.api('state',thread_id=tid)['checkpoint_id'],checkpoint)
