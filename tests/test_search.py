import copy
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from plan_fixture import valid_plan
from research_assistant.graph import build_graph


def hit(url='https://example.org/docs', title='Документация', snippet='Фрагмент'):
    return {'title': title, 'url': url, 'snippet': snippet}


class SearchGraphTests(unittest.TestCase):
    def start(self, searcher, plan=None):
        generator = Mock(return_value=valid_plan() if plan is None else plan)
        graph = build_graph(generator, review=True, search=True,
                            checkpointer=InMemorySaver(), search_function=searcher)
        config = {'configurable': {'thread_id': 'search-test'}}
        state = {'topic': '  Память\tагентов '}
        paused = graph.invoke(state, config)
        self.assertEqual(state, {'topic': '  Память\tагентов '})
        self.assertEqual(paused['status'], 'planned')
        self.assertNotIn('sources', paused)
        searcher.assert_not_called()
        return graph, config, generator

    def test_approve_queries_merge_urls_and_keep_order(self):
        shared = hit()
        responses = [[shared, shared, hit('https://example.org/other')],
                     [hit(title='Позднее название')], [hit('https://example.org/other')]]
        original = copy.deepcopy(responses)
        queries = [' '.join(['Память агентов', s['title'], *s['questions']]) for s in valid_plan()['sections']]
        searcher = Mock(side_effect=lambda query: responses[queries.index(query)])
        graph, config, generator = self.start(searcher)
        final = graph.invoke(Command(resume={'action': 'approve'}), config)
        self.assertEqual(final['status'], 'sources_found')
        self.assertEqual(final['topic'], '  Память\tагентов ')
        self.assertEqual(final['plan'], valid_plan())
        self.assertCountEqual([c.args[0] for c in searcher.call_args_list], [
            ' '.join(['Память агентов', s['title'], *s['questions']])
            for s in valid_plan()['sections']])
        self.assertEqual(final['sources'], [
            {**hit(), 'section_indexes': [0, 1]},
            {**hit('https://example.org/other'), 'section_indexes': [0, 2]}])
        self.assertEqual(responses, original)
        generator.assert_called_once()
        json.dumps(final, ensure_ascii=False)

    def test_edit_searches_only_final_sections_without_hidden_count_limit(self):
        searcher = Mock(return_value=[])
        graph, config, generator = self.start(searcher)
        edited = {'title': 'Новый план', 'sections': [
            {'title': f'Раздел {i}', 'questions': ['Новый вопрос?']} for i in range(6)]}
        final = graph.invoke(Command(resume={'action': 'edit', 'plan': edited}), config)
        self.assertEqual(final['status'], 'no_sources')
        self.assertEqual(final['sources'], [])
        self.assertEqual(final['plan'], edited)
        self.assertEqual(searcher.call_count, 6)
        self.assertEqual(searcher.call_args_list[0].args[0], 'Память агентов Раздел 0 Новый вопрос?')
        generator.assert_called_once()

    def test_cancel_needs_no_search_key_or_client(self):
        searcher = Mock()
        graph, config, generator = self.start(searcher)
        with patch.dict(os.environ, {}, clear=True), patch('research_assistant.search.TavilyClient') as client:
            final = graph.invoke(Command(resume={'action': 'cancel'}), config)
        self.assertEqual(final['status'], 'cancelled')
        self.assertNotIn('sources', final)
        searcher.assert_not_called()
        client.assert_not_called()
        generator.assert_called_once()

    def test_old_modes_do_not_search(self):
        for review in (False, True):
            searcher = Mock()
            config = {'configurable': {'thread_id': 'old'}}
            graph = build_graph(lambda _: valid_plan(), review=review,
                                checkpointer=InMemorySaver() if review else None,
                                search_function=searcher)
            final = graph.invoke({'topic': 'Python'}, config)
            if review:
                final = graph.invoke(Command(resume={'action': 'approve'}), config)
            self.assertEqual(final['status'], 'approved' if review else 'planned')
            self.assertNotIn('sources', final)
            searcher.assert_not_called()

    def test_search_failure_does_not_commit_partial_success(self):
        from research_assistant.search import SearchError
        def search(query):
            if valid_plan()['sections'][1]['title'] in query:
                raise SearchError('Ошибка поиска')
            return [hit()]
        searcher = Mock(side_effect=search)
        graph, config, generator = self.start(searcher)
        with self.assertRaises(SearchError):
            graph.invoke(Command(resume={'action': 'approve'}), config)
        snapshot = graph.get_state(config).values
        self.assertEqual(snapshot['status'], 'approved')
        self.assertNotIn('sources', snapshot)
        self.assertGreaterEqual(searcher.call_count, 2)
        self.assertLessEqual(searcher.call_count, 3)
        generator.assert_called_once()

    def test_invalid_hits_are_errors_and_urls_are_not_canonicalized(self):
        from research_assistant.search import SearchError
        for response in (None, {}, [None], [hit(title=' ')], [hit(url='file:///local')],
                         [hit(snippet=None)], [hit(url='javascript:alert(1)')]):
            with self.subTest(response=response):
                searcher = Mock(return_value=response)
                graph, config, _ = self.start(searcher)
                with self.assertRaises(SearchError):
                    graph.invoke(Command(resume={'action': 'approve'}), config)
        searcher = Mock(return_value=[hit('https://example.org'), hit('https://example.org/')])
        graph, config, _ = self.start(searcher)
        result = graph.invoke(Command(resume={'action': 'approve'}), config)
        self.assertEqual(len(result['sources']), 2)

    def test_node_returns_partial_update_without_mutating_state(self):
        from research_assistant.graph import prepare_search, search_section, collect_sources
        state = {'topic': ' Тема ', 'normalized_topic': 'Тема',
                 'status': 'approved', 'plan': valid_plan()}
        original = copy.deepcopy(state)
        prepared = prepare_search(state)
        batches = [batch for job in prepared['search_jobs']
                   for batch in search_section(job, Mock(return_value=[hit()]))['search_batches']]
        result = collect_sources({**state, **prepared, 'search_batches': batches})
        self.assertEqual(set(result), {'sources', 'status'})
        self.assertEqual(state, original)

    def test_long_query_is_rejected_without_truncation_or_any_search(self):
        from research_assistant.search import SearchError
        plan = valid_plan()
        plan['sections'][-1]['questions'] = ['Я' * 401]
        searcher = Mock()
        graph, config, _ = self.start(searcher, plan)
        with self.assertRaisesRegex(SearchError, '400'):
            graph.invoke(Command(resume={'action': 'approve'}), config)
        searcher.assert_not_called()

    def test_search_requires_review(self):
        with self.assertRaisesRegex(ValueError, 'review'):
            build_graph(search=True)

    def test_plan_without_sections_gives_no_sources_without_client(self):
        searcher = Mock()
        graph, config, generator = self.start(searcher, {'title': 'План', 'sections': []})
        final = graph.invoke(Command(resume={'action': 'approve'}), config)
        self.assertEqual(final['status'], 'no_sources')
        self.assertEqual(final['sources'], [])
        searcher.assert_not_called()
        generator.assert_called_once()


class SearchCliTests(unittest.TestCase):
    def run_cli(self, flags, answers=(), error=None):
        from research_assistant.cli import main
        out, err = StringIO(), StringIO()
        stdin = Mock()
        stdin.isatty.return_value = True
        with patch('sys.stdin', stdin), patch('builtins.input', side_effect=answers):
            with patch('research_assistant.graph.generate_research_plan', return_value=valid_plan()) as generator:
                with patch('research_assistant.graph.search_web', return_value=[hit()], side_effect=error) as searcher:
                    with redirect_stdout(out), redirect_stderr(err):
                        code = main(['--topic', 'Память', *flags])
        return code, out.getvalue(), err.getvalue(), generator, searcher

    def test_search_without_review_rejected_before_apis(self):
        code, out, err, generator, searcher = self.run_cli(['--search'])
        self.assertEqual(code, 2)
        self.assertEqual(out, '')
        self.assertIn('--review', err)
        generator.assert_not_called()
        searcher.assert_not_called()

    def test_cli_success_and_cancel_have_only_json_stdout(self):
        for answer, status in (('1', 'sources_found'), ('3', 'cancelled')):
            code, out, err, generator, searcher = self.run_cli(['--review', '--search'], [answer])
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)['status'], status)
            self.assertIn('Память', out)
            self.assertNotIn('__interrupt__', out)
            self.assertIn('утвердить', err)
            self.assertEqual(searcher.call_count, 3 if answer == '1' else 0)
            generator.assert_called_once()

    def test_cli_search_error_has_no_success_json(self):
        from research_assistant.search import SearchError
        code, out, err, _, _ = self.run_cli(['--review', '--search'], ['1'], SearchError('Ошибка поиска'))
        self.assertEqual(code, 2)
        self.assertEqual(out, '')
        self.assertIn('Ошибка поиска', err)
