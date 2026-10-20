import json
import os
import unittest
from unittest.mock import patch

import requests
from requests.adapters import BaseAdapter
from requests.models import Response

from research_assistant.search import SearchError, search_web


class LocalAdapter(BaseAdapter):
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def send(self, request, **kwargs):
        self.calls.append((request, kwargs))
        status, body = self.handler(request, kwargs)
        response = Response()
        response.status_code = status
        response._content = body.encode('utf-8')
        response.headers['Content-Type'] = 'application/json'
        response.request = request
        response.url = request.url
        return response

    def close(self):
        pass


class SearchProviderTests(unittest.TestCase):
    def invoke_local(self, handler, query='Память агентов'):
        adapter = LocalAdapter(handler)
        real_session = requests.Session

        def local_session():
            session = real_session()
            session.mount('https://', adapter)
            session.mount('http://', adapter)
            return session

        with patch.dict(os.environ, {'TAVILY_API_KEY': 'test-key'}, clear=True):
            with patch('research_assistant.search.load_dotenv'):
                with patch('research_assistant.search.requests.Session', side_effect=local_session):
                    result = search_web(query)
        return result, adapter

    def test_real_sdk_request_parameters_and_normalization(self):
        def handler(request, kwargs):
            self.assertEqual(request.url, 'https://api.tavily.com/search')
            body = json.loads(request.body)
            self.assertEqual(body, {
                'query': 'Память агентов', 'search_depth': 'basic', 'max_results': 1,
                'include_answer': False, 'include_raw_content': False, 'auto_parameters': False,
            })
            self.assertEqual(kwargs['timeout'], 30)
            return 200, json.dumps({'results': [
                {'title': ' Документация ', 'url': ' https://example.org ', 'content': 'Фрагмент', 'score': 0.9},
                {'title': 'Пустой фрагмент', 'url': 'http://example.net', 'content': ''},
                {'title': 'Без фрагмента', 'url': 'https://example.com'}]})
        result, adapter = self.invoke_local(handler)
        self.assertEqual(result, [
            {'title': 'Документация', 'url': 'https://example.org', 'snippet': 'Фрагмент'},
            {'title': 'Пустой фрагмент', 'url': 'http://example.net', 'snippet': ''},
            {'title': 'Без фрагмента', 'url': 'https://example.com', 'snippet': ''}])
        self.assertEqual(len(adapter.calls), 1)

    def test_empty_results(self):
        result, _ = self.invoke_local(lambda *_: (200, '{"results": []}'))
        self.assertEqual(result, [])

    def test_snippet_length_boundary_preserves_source_metadata(self):
        for size in (0, 499, 500, 501, 2000):
            with self.subTest(size=size):
                content = 'Я' * size
                result, _ = self.invoke_local(lambda *_: (200, json.dumps({'results': [
                    {'title': 'Источник', 'url': 'https://example.org', 'content': content}
                ]})))
                self.assertEqual(result, [{'title': 'Источник', 'url': 'https://example.org',
                                           'snippet': content[:500]}])

    def test_malformed_response_is_not_empty_success(self):
        invalid = ['not json', '{}', 'null', '[]', '{"results": null}', '{"results": {}}']
        for item in (None, {}, {'title': ' ', 'url': 'https://example.org', 'content': ''},
                     {'title': 'Title', 'url': 'ftp://example.org', 'content': ''},
                     {'title': 'Title', 'url': 'https://example.org', 'content': None}):
            invalid.append(json.dumps({'results': [item]}))
        for body in invalid:
            with self.subTest(body=body), self.assertRaises(SearchError):
                self.invoke_local(lambda *_: (200, body))

    def test_expected_http_errors_are_sanitized_and_not_retried(self):
        for status in (201, 204, 302, 400, 401, 403, 429, 432, 433, 500):
            calls = []
            def handler(*_):
                calls.append(status)
                return status, '{"detail": {"error": "private-key-or-body"}}'
            with self.subTest(status=status), self.assertRaises(SearchError) as raised:
                self.invoke_local(handler)
            self.assertNotIn('private-key-or-body', str(raised.exception))
            self.assertEqual(calls, [status])

    def test_timeout_connection_and_invalid_json_are_sanitized(self):
        for error in (requests.Timeout('private-data'), requests.ConnectionError('private-data')):
            def handler(*_):
                raise error
            with self.subTest(error=error), self.assertRaises(SearchError) as raised:
                self.invoke_local(handler)
            self.assertNotIn('private-data', str(raised.exception))

    def test_missing_key_and_overlong_query_before_client_creation(self):
        with patch.dict(os.environ, {}, clear=True), patch('research_assistant.search.load_dotenv'):
            with patch('research_assistant.search.TavilyClient') as client:
                for query, message in (('Python', 'TAVILY_API_KEY'), ('Я' * 401, '400')):
                    with self.subTest(query=query), self.assertRaisesRegex(SearchError, message):
                        search_web(query)
                client.assert_not_called()

    def test_exact_query_length_boundary_and_unexpected_error_propagates(self):
        query = 'Я' * 400
        def handler(request, _):
            self.assertEqual(json.loads(request.body)['query'], query)
            return 200, '{"results": []}'
        self.invoke_local(handler, query=query)
        with patch.dict(os.environ, {'TAVILY_API_KEY': 'test-key'}, clear=True):
            with patch('research_assistant.search.load_dotenv'):
                with patch('research_assistant.search.TavilyClient', side_effect=RuntimeError('bug')):
                    with self.assertRaisesRegex(RuntimeError, 'bug'):
                        search_web('Python')
