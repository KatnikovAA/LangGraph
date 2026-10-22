import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from research_assistant.interview.graph import build_interview_graph
from research_assistant.interview.demo import demo_analyst, demo_expert, demo_synthesis, demo_search
from research_assistant.interview.progress import project_progress


class ProgressTests(unittest.TestCase):
    def test_running_precedes_completion_and_rounds_distinct(self):
        entered, release, observed = threading.Event(), threading.Event(), threading.Event()
        events = []
        def expert(*args):
            entered.set()
            release.wait(5)
            return demo_expert(*args)
        with tempfile.TemporaryDirectory() as root:
            graph = build_interview_graph(analyst=demo_analyst, expert=expert,
                summarizer=demo_synthesis, search_function=demo_search, output_dir=root)
            def consume():
                for mode, event in graph.stream({'topic': 'x'}, {'configurable': {'thread_id': 'p'}}, stream_mode=['custom', 'updates']):
                    if mode == 'custom':
                        events.append(event)
                        if event['node'] == 'answer_question' and event['status'] == 'running':
                            observed.set()
            with ThreadPoolExecutor() as pool:
                future = pool.submit(consume)
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertTrue(observed.wait(5))
                    self.assertFalse(any(e['node'] == 'answer_question' and e['status'] == 'done' for e in events))
                finally:
                    release.set()
                future.result()
        asks = [e for e in events if e['node'] == 'ask_question' and e['status'] == 'running']
        self.assertEqual([e['round'] for e in asks], [1, 2])
        self.assertNotEqual(asks[0]['execution_id'], asks[1]['execution_id'])
        event = project_progress({**asks[0], 'secret': 'private', 'run_id': 'fake'}, 'real')
        self.assertNotIn('secret', event)
        self.assertEqual(event['run_id'], 'real')
        self.assertIsNone(project_progress({**asks[0], 'node': 'unknown'}, 'real'))

    def test_error_is_not_done(self):
        with tempfile.TemporaryDirectory() as root:
            def broken(*args):
                raise RuntimeError('secret')
            graph = build_interview_graph(analyst=broken, output_dir=root)
            events = []
            with self.assertRaises(Exception):
                for event in graph.stream({'topic': 'x'}, stream_mode='custom'):
                    events.append(event)
            statuses = [e['status'] for e in events if e['node'] == 'ask_question']
            self.assertEqual(statuses, ['running', 'error'])
            self.assertNotIn('secret', str(events))
