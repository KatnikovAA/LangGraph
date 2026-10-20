import json
import os
import unittest
from unittest.mock import patch

import httpx
from langchain_openai import ChatOpenAI

from research_assistant.reporting import generate_report_draft, ReportError
from test_reporting import draft, plan


class ReportProviderTests(unittest.TestCase):
    def invoke(self, handler):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            def local_model(**kwargs):
                return ChatOpenAI(**kwargs, http_client=client)
            with patch.dict(os.environ, {'POLZA_API_KEY': 'test-secret', 'POLZA_MODEL': 'provider/test',
                                         'POLZA_BASE_URL': 'https://polza.ai/api/v1/'}, clear=True), \
                 patch('research_assistant.planning.load_dotenv'), \
                 patch('research_assistant.planning.ChatOpenAI', side_effect=local_model):
                return generate_report_draft('Тема', plan(), [{'id': 'S1', 'title': 'Источник', 'snippet': 'Данные'}])

    def response(self, content, finish='stop'):
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 0,
            'model': 'provider/test', 'choices': [{'index': 0, 'finish_reason': finish,
            'message': {'role': 'assistant', 'content': content}}]})

    def test_structured_single_request_and_minimal_payload(self):
        calls = []
        def handler(request):
            body = json.loads(request.content)
            calls.append(body)
            self.assertEqual(body['response_format']['json_schema']['name'], 'ReportDraft')
            self.assertNotIn('max_completion_tokens', body)
            self.assertNotIn('max_tokens', body)
            self.assertNotIn('test-secret', json.dumps(body))
            human = json.loads(body['messages'][-1]['content'])
            self.assertEqual(set(human), {'topic', 'plan', 'sources'})
            self.assertEqual(set(human['sources'][0]), {'id', 'title', 'snippet'})
            self.assertIn('до 200 слов', body['messages'][0]['content'])
            return self.response(json.dumps(draft()))
        result = self.invoke(handler)
        self.assertEqual(result.model_dump(), draft())
        self.assertEqual(len(calls), 1)

    def test_expected_errors_are_sanitized_no_retry_and_unexpected_propagate(self):
        for kind in ['invalid', 'http', 'length', 'network']:
            with self.subTest(kind=kind):
                calls = []
                def handler(request):
                    calls.append(request)
                    if kind == 'network':
                        raise httpx.ConnectError('private-response', request=request)
                    if kind == 'http':
                        return httpx.Response(500, json={'error': {'message': 'private-response'}})
                    return self.response('{}' if kind == 'invalid' else '{}', 'length' if kind == 'length' else 'stop')
                with self.assertRaises(ReportError) as caught:
                    self.invoke(handler)
                self.assertNotIn('private-response', str(caught.exception))
                self.assertEqual(len(calls), 1)
        with patch('research_assistant.reporting.create_model', side_effect=RuntimeError('bug')):
            with self.assertRaisesRegex(RuntimeError, 'bug'):
                generate_report_draft('Тема', plan(), [])
