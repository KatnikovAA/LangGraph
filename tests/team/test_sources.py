import copy
import tempfile
import unittest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from research_assistant.team.graph import build_team_graph
from research_assistant.team.demo import team_analyst,team_expert,team_synthesis,team_search,team_report
from research_assistant.team.sources import collect_team_sources,remap_source_ids
from research_assistant.team.schemas import merge_worker_results


class SourceTests(unittest.TestCase):
    def test_mapping_origin_and_reducer(self):
        with tempfile.TemporaryDirectory() as root:
            graph=build_team_graph(analyst=team_analyst,expert=team_expert,summarizer=team_synthesis,
                search_function=team_search,team_summarizer=team_report,checkpointer=InMemorySaver(),output_dir=root)
            config={'configurable':{'thread_id':'s'}}
            graph.invoke({'topic':'x'},config)
            result=graph.invoke(Command(resume={'action':'approve'}),config)
        a,b=result['worker_results'];original=copy.deepcopy([a,b])
        merged=collect_team_sources([b,a])
        self.assertEqual(merged['source_mapping'],{'A':{'S1':'S1'},'B':{'S1':'S2'}})
        self.assertEqual([a,b],original)
        self.assertEqual(merge_worker_results([a],[a,b]),[a,b])
        conflict={**a,'limitations':['changed']}
        with self.assertRaises(ValueError):merge_worker_results([a],[conflict])
        b=copy.deepcopy(b);b['sources'][0]['url']=a['sources'][0]['url']
        dedup=collect_team_sources([a,b])
        self.assertEqual(len(dedup['sources']),1)
        self.assertEqual(len(dedup['source_origins']['S1']),2)
        self.assertNotEqual(a['sources'][0]['snippet'],b['sources'][0]['snippet'])
        with self.assertRaises(ValueError):collect_team_sources([a])
        with self.assertRaises(ValueError):remap_source_ids(['S999'],{'S1':'S1'})
