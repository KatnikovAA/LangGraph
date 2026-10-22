import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from langgraph.checkpoint.memory import InMemorySaver
from research_assistant.interview.graph import build_interview_graph
from research_assistant.interview.demo import demo_analyst, demo_expert, demo_synthesis, demo_search


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {'configurable': {'thread_id': 'interview-test'}}
        self.calls = {'analyst': 0, 'expert': 0, 'summary': 0, 'search': 0}
        self.seen = []

    def build(self, fail=False, empty=False, bad=False):
        def analyst(*args):
            self.calls['analyst'] += 1
            self.seen.append(args[-1])
            return demo_analyst(*args)
        def expert(*args):
            self.calls['expert'] += 1
            if fail and self.calls['expert'] == 2:
                raise RuntimeError('private provider detail')
            return {'text': 'bad', 'source_ids': ['S999']} if bad else demo_expert(*args)
        def summary(*args):
            self.calls['summary'] += 1
            return demo_synthesis(*args)
        def search(query):
            self.calls['search'] += 1
            return [] if empty else demo_search(query)
        return build_interview_graph(analyst=analyst, expert=expert, summarizer=summary,
            search_function=search, checkpointer=InMemorySaver(), output_dir=self.tmp.name)

    def test_two_rounds_budget_and_second_context(self):
        result = self.build().invoke({'topic': 'LangGraph', 'clarification': 'Надёжность'}, self.config)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['transcript']), 2)
        self.assertNotEqual(result['questions'][0], result['questions'][1])
        self.assertEqual(self.seen[1][0]['answer'], result['answers'][0])
        self.assertEqual(self.calls, dict(analyst=2, expert=2, summary=1, search=2))
        self.assertTrue(Path(result['report_path']).is_file())

    def test_empty_and_bad_output(self):
        result = self.build(empty=True).invoke({'topic': 'x'}, self.config)
        self.assertEqual(result['sources'], [])
        self.assertEqual(len(result['transcript']), 2)
        self.assertTrue(result['limitations'])
        self.assertIn('Недостаточно', result['answers'][0]['text'])
        with self.assertRaises(ValueError):
            self.build(bad=True).invoke({'topic': 'x'}, self.config)

    def test_resume_failed_second_answer(self):
        graph = self.build(fail=True)
        with self.assertRaises(Exception):
            graph.invoke({'topic': 'x'}, self.config)
        self.assertEqual(len(graph.get_state(self.config).values['transcript']), 1)
        result = graph.invoke(None, self.config)
        self.assertEqual(len(result['transcript']), 2)
        self.assertEqual(self.calls, dict(analyst=2, expert=3, summary=1, search=2))

    def test_write_retry_does_not_repeat_synthesis(self):
        graph = self.build()
        with patch('research_assistant.interview.graph.write_report', side_effect=OSError('disk')):
            with self.assertRaises(Exception):
                graph.invoke({'topic': 'x'}, self.config)
        result = graph.invoke(None, self.config)
        self.assertEqual(self.calls['summary'], 1)
        self.assertEqual(len(list(Path(self.tmp.name).glob('*.md'))), 1)
        self.assertEqual(result['status'], 'completed')

    def test_report_unknown_id_and_duplicate_question_rejected(self):
        kwargs=dict(analyst=demo_analyst,expert=demo_expert,summarizer=lambda *a: {
            'title':'Report','sections':[{'title':'x','text':'x','source_ids':['S999']}]},
            search_function=demo_search,output_dir=self.tmp.name)
        with self.assertRaises(Exception):
            build_interview_graph(**kwargs).invoke({'topic':'x'},self.config)
        kwargs['summarizer']=demo_synthesis
        kwargs['analyst']=lambda *a: {'text':'same question','search_query':'query'}
        with self.assertRaises(ValueError):
            build_interview_graph(**kwargs).invoke({'topic':'x'},self.config)

    def test_sqlite_resume_after_reopen(self):
        from langgraph.checkpoint.sqlite import SqliteSaver
        failed=[False]
        def expert(*args):
            if 'В первом ответе' in args[0]['text'] and not failed[0]:
                failed[0]=True
                raise ValueError('once')
            return demo_expert(*args)
        database=str(Path(self.tmp.name)/'checkpoints.sqlite')
        options=dict(analyst=demo_analyst,expert=expert,summarizer=demo_synthesis,
                     search_function=demo_search,output_dir=self.tmp.name)
        with SqliteSaver.from_conn_string(database) as saver:
            graph=build_interview_graph(checkpointer=saver,**options)
            with self.assertRaises(ValueError):
                graph.invoke({'topic':'x'},self.config)
        with SqliteSaver.from_conn_string(database) as saver:
            graph=build_interview_graph(checkpointer=saver,**options)
            self.assertEqual(len(graph.get_state(self.config).values['transcript']),1)
            result=graph.invoke(None,self.config)
        self.assertEqual(len(result['transcript']),2)
