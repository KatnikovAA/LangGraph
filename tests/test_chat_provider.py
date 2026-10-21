import json
import unittest
from unittest.mock import patch

import httpx
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from research_assistant.chat import ChatError, build_chat_graph, initialize_chat
from test_chat import FakeModel, materials


def response(content='', calls=None):
    message = {'role': 'assistant', 'content': content}
    if calls is not None:
        message['tool_calls'] = calls
    return httpx.Response(200, json={'id': 'local-chat', 'object': 'chat.completion', 'created': 0,
        'model': 'provider/test', 'choices': [{'index': 0, 'finish_reason': 'tool_calls' if calls else 'stop', 'message': message}]})


class ChatProviderTests(unittest.TestCase):
    def run_with_http(self, handler):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            model = ChatOpenAI(model='provider/test', api_key='offline-secret', base_url='https://polza.ai/api/v1/',
                               http_client=client, max_retries=0, use_responses_api=False)
            graph = build_chat_graph(checkpointer=InMemorySaver(), model_factory=lambda: model)
            config = {'configurable': {'thread_id': 'http-chat'}}
            initialize_chat(graph, config, materials(), 'db')
            return graph.invoke({'question': 'Что в S1?'}, config)

    def test_bind_tools_actual_request_response_and_no_hard_output_limit(self):
        calls = []
        def handler(request):
            body = json.loads(request.content)
            calls.append(body)
            self.assertEqual(body['model'], 'provider/test')
            schema = body['tools'][0]['function']
            self.assertEqual(schema['name'], 'get_source')
            self.assertEqual(set(schema['parameters']['properties']), {'source_id'})
            self.assertNotIn('max_completion_tokens', body)
            self.assertNotIn('max_tokens', body)
            self.assertNotIn('offline-secret', json.dumps(body))
            self.assertEqual(sum(m['role'] == 'system' for m in body['messages']), 1)
            if len(calls) == 1:
                return response(calls=[{'id': 'call-real', 'type': 'function', 'function': {
                    'name': 'get_source', 'arguments': '{"source_id":"S1"}'}}])
            tool_result = body['messages'][-1]
            self.assertEqual(tool_result['role'], 'tool')
            self.assertEqual(tool_result['tool_call_id'], 'call-real')
            self.assertEqual(json.loads(tool_result['content'])['snippet'], 'Фрагмент')
            return response('Сохранённый источник содержит фрагмент.')
        result = self.run_with_http(handler)
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(len(calls), 2)

    def test_unsupported_http_network_and_invalid_calls_are_sanitized(self):
        for mode in ['http', 'network', 'bad_arguments']:
            with self.subTest(mode=mode):
                calls = []
                def handler(request):
                    calls.append(request)
                    if mode == 'http':
                        return httpx.Response(400, json={'error': {'message': 'offline-secret tools not supported'}})
                    if mode == 'network':
                        raise httpx.ConnectError('offline-secret', request=request)
                    return response(calls=[{'id': 'bad', 'type': 'function', 'function': {
                        'name': 'get_source', 'arguments': '{invalid'}}])
                with self.assertRaises(ChatError) as caught:
                    self.run_with_http(handler)
                self.assertNotIn('offline-secret', str(caught.exception))
                self.assertEqual(len(calls), 1)
        unsupported = FakeModel([])
        with patch.object(unsupported, 'bind_tools', side_effect=NotImplementedError('private detail')):
            graph = build_chat_graph(checkpointer=InMemorySaver(), model_factory=lambda: unsupported)
            config = {'configurable': {'thread_id': 'unsupported'}}
            initialize_chat(graph, config, materials(), 'db')
            with self.assertRaisesRegex(ChatError, 'Tool Calling'):
                graph.invoke({'question': 'Вопрос'}, config)

    def test_unexpected_error_is_not_hidden(self):
        model = FakeModel([RuntimeError('program bug')])
        graph = build_chat_graph(checkpointer=InMemorySaver(), model_factory=lambda: model)
        config = {'configurable': {'thread_id': 'bug'}}
        initialize_chat(graph, config, materials(), 'db')
        with self.assertRaisesRegex(RuntimeError, 'program bug'):
            graph.invoke({'question': 'Вопрос'}, config)
