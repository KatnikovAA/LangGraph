import tempfile
import threading
import unittest
from unittest.mock import patch
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from research_assistant.team.graph import build_team_graph
from research_assistant.team.schemas import validate_roles, default_roles
from research_assistant.team.demo import team_analyst, team_expert, team_synthesis, team_search, team_report


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.config={'configurable':{'thread_id':'team'},'max_concurrency':2}
        self.calls=[];self.lock=threading.Lock()
        self.searches=[]

    def build(self,barrier=None):
        def analyst(topic,clarification,role,transcript,*,focus=''):
            if barrier and not transcript: barrier.wait(timeout=5)
            with self.lock:self.calls.append(('analyst',role,focus))
            return team_analyst(topic,clarification,role,transcript,focus=focus)
        def expert(*args):
            with self.lock:self.calls.append(('expert',))
            return team_expert(*args)
        def synthesis(*args):
            with self.lock:self.calls.append(('synthesis',))
            return team_synthesis(*args)
        def report(*args):
            self.calls.append(('report',));return team_report(*args)
        def search(*args):
            with self.lock:self.searches.append(args)
            return team_search(*args)
        return build_team_graph(analyst=analyst,expert=expert,summarizer=synthesis,
            search_function=search,team_summarizer=report,checkpointer=InMemorySaver(),output_dir=self.tmp.name)

    def test_cancel_and_validation(self):
        graph=self.build();graph.invoke({'topic':'topic'},self.config)
        self.assertEqual(self.calls,[])
        result=graph.invoke(Command(resume={'action':'cancel'}),self.config)
        self.assertEqual(result['status'],'cancelled');self.assertEqual(self.calls,[])
        for roles in ([],default_roles()[:1],default_roles()+default_roles()[:1],
                      [default_roles()[0],default_roles()[0]]):
            with self.assertRaises(ValueError):validate_roles(roles)

    def test_parallel_edit_budget_isolation(self):
        graph=self.build(threading.Barrier(2))
        graph.invoke({'topic':'topic'},self.config)
        roles=default_roles();roles[0]['focus']='Custom focus A'
        result=graph.invoke(Command(resume={'action':'edit','roles':roles}),self.config)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len(self.calls),11)
        self.assertEqual(len(self.searches),4)
        self.assertEqual([r['analyst_id'] for r in result['worker_results']],['A','B'])
        self.assertTrue(any(c[0]=='analyst' and c[-1]=='Custom focus A' for c in self.calls))
        a,b=result['worker_results']
        self.assertNotEqual(a['transcript'][0]['question']['text'],b['transcript'][0]['question']['text'])
        self.assertIn(a['answers'][0]['text'][:80],a['questions'][1]['text'])

    def test_save_retry_does_not_repeat_interviews_or_synthesis(self):
        graph=self.build()
        graph.invoke({'topic':'topic'},self.config)
        with patch('research_assistant.team.graph.write_report',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                graph.invoke(Command(resume={'action':'approve'}),self.config)
        self.assertEqual(graph.get_state(self.config).next,('save_report',))
        calls=list(self.calls);searches=list(self.searches)
        result=graph.invoke(None,self.config)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(self.calls,calls)
        self.assertEqual(self.searches,searches)
