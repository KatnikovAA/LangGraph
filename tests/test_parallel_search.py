import copy
import tempfile
import threading
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import Mock, patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from research_assistant.graph import build_graph
from research_assistant.persistence import open_saver, workflow_settings
from research_assistant.search import SearchError
from test_reporting import draft


def parallel_plan(count=3):
    return {'title': 'Plan', 'sections': [{'title': f'Section{i}', 'questions': ['Q?']} for i in range(count)]}


def hit(index):
    return {'title': f'Source{index}', 'url': f'https://example.org/{index}', 'snippet': f'Data{index}'}


def index_of(query):
    return int(query.split('Section')[1].split()[0])


class ParallelSearchTests(unittest.TestCase):
    def start(self, searcher, count=3, **kwargs):
        graph = build_graph(lambda t: parallel_plan(count), review=True, search=True,
                            search_function=searcher, checkpointer=InMemorySaver(), **kwargs)
        config = {'configurable': {'thread_id': 'parallel'}, 'max_concurrency': 2}
        graph.invoke({'topic': 'Topic'}, config)
        return graph, config

    def test_overlap_limit_order_dedup_and_single_fanin_report(self):
        lock = threading.Lock()
        both_started = threading.Event()
        second_done = threading.Event()
        active, peak = 0, 0
        completed = []
        def search(query):
            nonlocal active, peak
            index = index_of(query)
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    both_started.set()
            try:
                if index in (0, 1):
                    self.assertTrue(both_started.wait(5), 'Workers did not overlap')
                if index == 0:
                    self.assertTrue(second_done.wait(5), 'Second worker did not finish')
                with lock:
                    completed.append(index)
                if index == 1:
                    second_done.set()
                shared = {**hit('shared'), 'title': f'Title{index}'}
                return [shared, hit(index)]
            finally:
                with lock:
                    active -= 1
        def report(*args):
            self.assertEqual(set(completed), {0, 1, 2, 3})
            return draft()
        from research_assistant.graph import collect_sources
        reporter = Mock(side_effect=report)
        with tempfile.TemporaryDirectory() as root, \
             patch('research_assistant.graph.collect_sources', wraps=collect_sources) as collector:
            graph, config = self.start(search, count=4, report=True, output_dir=root, report_generator=reporter)
            result = graph.invoke(Command(resume={'action': 'approve'}), config)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(peak, 2)
            self.assertLess(completed.index(1), completed.index(0))
            self.assertEqual([s['url'] for s in result['sources']],
                             [hit('shared')['url']] + [hit(i)['url'] for i in range(4)])
            self.assertEqual(result['sources'][0]['title'], 'Title0')
            self.assertEqual(result['sources'][0]['section_indexes'], [0, 1, 2, 3])
            self.assertEqual(len(result['search_batches']), 4)
            collector.assert_called_once()
            reporter.assert_called_once()

    def test_one_section_one_worker_empty_and_cancel_no_worker(self):
        for count, action, calls, status in [(1, 'approve', 1, 'sources_found'),
                                              (0, 'approve', 0, 'no_sources'), (3, 'cancel', 0, 'cancelled')]:
            with self.subTest(count=count, action=action):
                searcher = Mock(return_value=[hit(0)])
                graph, config = self.start(searcher, count)
                result = graph.invoke(Command(resume={'action': action}), config)
                self.assertEqual(searcher.call_count, calls)
                self.assertEqual(result['status'], status)

    def test_prepare_worker_dispatcher_collector_contracts_and_no_mutation(self):
        from research_assistant.graph import prepare_search, search_section, collect_sources, dispatch_search
        state = {'topic': 'Topic', 'normalized_topic': 'Topic', 'status': 'approved', 'plan': parallel_plan(2)}
        original = copy.deepcopy(state)
        prepared = prepare_search(state)
        self.assertEqual(set(prepared), {'search_jobs'})
        self.assertEqual(state, original)
        sends = dispatch_search({**state, **prepared})
        self.assertEqual([s.node for s in sends], ['search_section', 'search_section'])
        results = [hit(0), hit(0)]
        original_results = copy.deepcopy(results)
        worker_input = prepared['search_jobs'][0]
        update = search_section(worker_input, lambda q: results)
        self.assertEqual(set(update), {'search_batches'})
        self.assertEqual(len(update['search_batches']), 1)
        self.assertEqual(worker_input, {'section_index': 0, 'query': 'Topic Section0 Q?'})
        self.assertEqual(results, original_results)
        all_state = {**state, **prepared, 'search_batches': update['search_batches'] + [{'section_index': 1, 'results': []}]}
        original_all = copy.deepcopy(all_state)
        collected = collect_sources(all_state)
        self.assertEqual(set(collected), {'sources', 'status'})
        self.assertEqual(all_state, original_all)
        for batches in [[], update['search_batches'] * 2,
                        [{'section_index': 2, 'results': []}, {'section_index': 0, 'results': []}]]:
            with self.subTest(batches=batches), self.assertRaises(SearchError):
                collect_sources({**all_state, 'search_batches': batches})

    def test_default_graph_and_cli_configs_limit_concurrency(self):
        from research_assistant.cli import main
        from contextlib import redirect_stdout, redirect_stderr
        from io import StringIO
        graph, config = self.start(Mock(return_value=[]))
        self.assertEqual(graph.config['max_concurrency'], 2)
        self.assertNotIn('max_concurrency', graph.config.get('configurable', {}))
        with tempfile.TemporaryDirectory() as root, \
             patch('research_assistant.cli.build_graph', wraps=build_graph) as builder, \
             patch('research_assistant.graph.generate_research_plan', return_value=parallel_plan(1)), \
             patch('research_assistant.cli.require_terminal'), \
             patch('research_assistant.cli.request_review', return_value={'action': 'cancel'}), \
             redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = main(['--topic', 'Topic', '--review', '--search', '--report', '--pause-after-plan',
                         '--checkpoint-db', str(Path(root) / 'db.sqlite')])
            self.assertEqual(code, 0)

    def test_version_one_thread_rejected_by_cli_without_api_or_db_deletion(self):
        from research_assistant.cli import main
        from contextlib import redirect_stdout, redirect_stderr
        from io import StringIO
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            config = {'configurable': {'thread_id': 'old'}}
            with open_saver(db) as saver:
                # The old workflow had no parallel search state or search worker nodes.
                old_graph = build_graph(lambda t: parallel_plan(1), review=True, checkpointer=saver)
                settings = {**workflow_settings(db, root, 'old'), 'version': 1}
                old_graph.invoke({'topic': 'Topic', 'workflow': settings}, config, durability='sync')
            out, err = StringIO(), StringIO()
            with patch('research_assistant.graph.generate_research_plan') as planner, \
                 patch('research_assistant.graph.search_web') as searcher, \
                 patch('research_assistant.graph.generate_report_draft') as reporter, \
                 redirect_stdout(out), redirect_stderr(err):
                code = main(['--resume', 'old', '--checkpoint-db', db])
            self.assertEqual(code, 2)
            self.assertEqual(out.getvalue(), '')
            self.assertIn('Несовместимая версия', err.getvalue())
            planner.assert_not_called()
            searcher.assert_not_called()
            reporter.assert_not_called()
            self.assertTrue(Path(db).is_file())
            with open_saver(db) as saver:
                self.assertEqual(old_graph.copy({'checkpointer': saver}).get_state(config).values['workflow']['version'], 1)

    def test_failed_worker_sqlite_pending_writes_new_connection_resume(self):
        calls = Counter()
        lock = threading.Lock()
        success_done = threading.Event()
        def search(query):
            index = index_of(query)
            with lock:
                calls[index] += 1
            if index == 0:
                success_done.set()
                return [hit(0)]
            self.assertTrue(success_done.wait(5))
            raise SearchError('Branch failed')
        reporter = Mock(return_value=draft())
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            config = {'configurable': {'thread_id': 'pending'}, 'max_concurrency': 2}
            with open_saver(db) as saver:
                graph = build_graph(lambda t: parallel_plan(2), review=True, search=True, report=True,
                                    output_dir=root, checkpointer=saver, search_function=search, report_generator=reporter)
                graph.invoke({'topic': 'Topic', 'workflow': workflow_settings(db, root, 'pending')}, config, durability='sync')
                with self.assertRaisesRegex(SearchError, 'Branch failed'):
                    graph.invoke(Command(resume={'action': 'approve'}), config, durability='sync')
                snapshot = graph.get_state(config)
                self.assertEqual(snapshot.values['status'], 'approved')
                self.assertNotIn('sources', snapshot.values)
                self.assertNotIn('report_markdown', snapshot.values)
                self.assertTrue(any(t.result for t in snapshot.tasks))
                reporter.assert_not_called()
                self.assertFalse(list(Path(root).glob('report-*.md')))
            def retry(query):
                index = index_of(query)
                self.assertEqual(index, 1, 'Successful Task was repeated')
                calls[index] += 1
                return [hit(1)]
            with open_saver(db) as saver:
                from research_assistant.graph import collect_sources
                forbidden = Mock(side_effect=AssertionError('Plan repeated'))
                with patch('research_assistant.graph.collect_sources', wraps=collect_sources) as collector:
                    graph = build_graph(forbidden, review=True, search=True, report=True, output_dir=root,
                                        checkpointer=saver, search_function=retry, report_generator=reporter)
                    result = graph.invoke(None, config, durability='sync')
                    self.assertEqual(result['status'], 'completed')
                    self.assertEqual([s['url'] for s in result['sources']], [hit(0)['url'], hit(1)['url']])
                    self.assertEqual(len(result['search_batches']), 2)
                    self.assertEqual(calls, {0: 1, 1: 2})
                    collector.assert_called_once()
                    reporter.assert_called_once()
                    forbidden.assert_not_called()
