import json
import os
import unittest
from unittest.mock import patch

import httpx
from langchain_openai import ChatOpenAI

from plan_fixture import valid_plan
from research_assistant.graph import build_graph
from research_assistant.planning import generate_research_plan, PlanGenerationError, ConfigurationError


class ProviderTests(unittest.TestCase):
    def invoke_with_transport(self, handler):
        def local_model(**kwargs):
            return ChatOpenAI(**kwargs, http_client=client)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with patch.dict(os.environ, {
                'POLZA_API_KEY': 'test-key', 'POLZA_MODEL': 'provider/test-model',
                'POLZA_BASE_URL': 'https://polza.ai/api/v1/',
            }, clear=True), patch('research_assistant.planning.load_dotenv'):
                with patch('research_assistant.planning.ChatOpenAI', side_effect=local_model):
                    return build_graph().invoke({'topic': '  Архитектура\tPython  '})

    def response(self, content):
        return httpx.Response(200, json={
            'id': 'offline-test', 'object': 'chat.completion', 'created': 0,
            'model': 'provider/test-model',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': content,
            }}],
        })

    def test_structured_request_and_response_without_network(self):
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(str(request.url), 'https://polza.ai/api/v1/chat/completions')
            self.assertEqual(body['model'], 'provider/test-model')
            self.assertNotIn('max_completion_tokens', body)
            self.assertNotIn('max_tokens', body)
            self.assertEqual(body['messages'][-1]['content'], 'Архитектура Python')
            self.assertEqual(body['response_format']['type'], 'json_schema')
            return self.response(json.dumps(valid_plan(), ensure_ascii=False))

        result = self.invoke_with_transport(handler)
        self.assertEqual(result['status'], 'planned')
        self.assertEqual(result['plan'], valid_plan())

    def test_token_limit_exceeded_is_an_error(self):
        def handler(request):
            response = self.response('{"title":')
            data = response.json()
            data['choices'][0]['finish_reason'] = 'length'
            return httpx.Response(200, json=data)
        with self.assertRaises(PlanGenerationError):
            self.invoke_with_transport(handler)

    def test_malformed_and_refused_responses(self):
        for content in ('not json', '{}', 'null'):
            with self.subTest(content=content), self.assertRaises(PlanGenerationError):
                self.invoke_with_transport(lambda request: self.response(content))

    def test_model_refusal(self):
        def handler(request):
            return httpx.Response(200, json={
                'id': 'refusal', 'object': 'chat.completion', 'created': 0,
                'model': 'provider/test-model',
                'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
                    'role': 'assistant', 'content': None, 'refusal': 'Cannot comply',
                }}],
            })
        with self.assertRaises(PlanGenerationError):
            self.invoke_with_transport(handler)

    def test_api_errors_do_not_expose_response_body(self):
        for status in (401, 429, 500):
            with self.subTest(status=status):
                def handler(request):
                    return httpx.Response(status, json={'error': {'message': 'private-provider-data'}})
                with self.assertRaises(PlanGenerationError) as raised:
                    self.invoke_with_transport(handler)
                self.assertNotIn('private-provider-data', str(raised.exception))
                self.assertIn(str(status), str(raised.exception))

    def test_connection_failure(self):
        def handler(request):
            raise httpx.ConnectError('offline', request=request)
        with self.assertRaisesRegex(PlanGenerationError, 'подключиться'):
            self.invoke_with_transport(handler)

    def test_model_must_be_selected(self):
        with patch.dict(os.environ, {'POLZA_API_KEY': 'test-key'}, clear=True):
            with patch('research_assistant.planning.load_dotenv'):
                with self.assertRaisesRegex(ConfigurationError, 'POLZA_MODEL'):
                    generate_research_plan('Python')
