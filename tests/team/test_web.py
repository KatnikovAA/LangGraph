import unittest
from uuid import uuid4
from research_assistant.team.progress import project_team_progress,team_public_state
from research_assistant.team.materials import team_materials


class WebTests(unittest.TestCase):
    def test_worker_events_safe(self):
        event=dict(analyst_id='B',node='answer_question',round=2,execution_id=str(uuid4()),
            timestamp='2026-10-22T10:00:00+00:00',status='error',secret='PRIVATE')
        result=project_team_progress(event,'real')
        self.assertEqual(result['analyst_id'],'B');self.assertEqual(result['run_id'],'real')
        self.assertNotIn('PRIVATE',str(result))
        self.assertIsNone(project_team_progress({**event,'analyst_id':'unknown'},'real'))

    def test_pending_subgraph_projection(self):
        child={'values':{'analyst_id':'B','analyst_role':'Risk','focus':'Cost','round':2,
                        'questions':[],'answers':[{'text':'first','source_ids':[]}],'secret':'PRIVATE'},
               'next':['answer_question'],'tasks':[{'error':'SECRET'}]}
        snapshot={'values':{'roles':[],'worker_results':[]},'next':['interview_worker'],
                  'tasks':[{'state':child,'error':'INTERNAL'}]}
        result=team_public_state(snapshot)
        self.assertTrue(result['workers']['B']['error'])
        self.assertEqual(result['workers']['B']['next'],['answer_question'])
        self.assertNotIn('PRIVATE',str(result));self.assertNotIn('INTERNAL',str(result))

    def test_invalid_team_materials_rejected(self):
        for value in ({},{'status':'completed','workflow':{'mode':'team','version':'old'}}):
            with self.assertRaises(ValueError):team_materials(value,'thread')
