import unittest
from unittest.mock import Mock, patch
from langgraph.checkpoint.memory import InMemorySaver
from research_assistant.interview.core import build_interview_core
from research_assistant.interview.demo import demo_analyst, demo_expert, demo_synthesis, demo_search
from research_assistant.interview.providers import ask_analyst


class CoreTests(unittest.TestCase):
    def test_core_no_file_and_five_calls(self):
        calls=[]
        def analyst(*args,focus=''):
            calls.append(('analyst',focus))
            return demo_analyst(*args)
        def expert(*args):
            calls.append(('expert',None));return demo_expert(*args)
        def synthesis(*args):
            calls.append(('summary',None));return demo_synthesis(*args)
        graph=build_interview_core(analyst=analyst,expert=expert,summarizer=synthesis,
                                   search_function=demo_search,checkpointer=InMemorySaver())
        result=graph.invoke({'topic':'LangGraph','analyst_id':'A','analyst_role':'Польза',
            'focus':'Практика'}, {'configurable':{'thread_id':'core'}})
        self.assertEqual(len(calls),5)
        self.assertEqual(calls[0],('analyst','Практика'))
        self.assertEqual(len(result['transcript']),2)
        self.assertNotIn('report_path',result)

    def test_role_focus_system_instruction(self):
        model=Mock()
        model.with_structured_output.return_value.invoke.return_value={'text':'Question','search_query':'Query'}
        with patch('research_assistant.interview.providers.create_model',return_value=model):
            ask_analyst('topic','clarification','Риски',[],focus='Отказы')
        system=model.with_structured_output.return_value.invoke.call_args.args[0][0][1]
        self.assertIn('Риски',system)
        self.assertIn('Отказы',system)
