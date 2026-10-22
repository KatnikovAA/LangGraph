import tempfile
import unittest


class JournalTests(unittest.TestCase):
    def test_request_payload_and_run_binding(self):
        from research_assistant.web.journal import RequestJournal
        with tempfile.TemporaryDirectory() as root:
            journal = RequestJournal(root)
            self.assertIsNone(journal.reserve('alice', 'request-one', {'topic': 'A'}))
            journal.bind_run('alice', 'request-one', 'thread', 'run')
            self.assertEqual(journal.reserve('alice', 'request-one', {'topic': 'A'})['run_id'], 'run')
            with self.assertRaises(ValueError):
                journal.reserve('alice', 'request-one', {'topic': 'B'})

    def test_safe_stream_filter(self):
        from research_assistant.web.client import public_event
        self.assertIsNone(public_event('values', {'secret': 'Store'}))
        self.assertIsNone(public_event('messages/partial', [{'type': 'tool', 'content': 'private'}]))
        self.assertIsNone(public_event('messages/partial', [{'type': 'ai', 'content': '', 'tool_calls': [{'args': 'private'}]}]))
        self.assertEqual(public_event('updates', {'agent': {'private': 1}}), ('progress', {'message': 'Формируем ответ'}))

    def test_store_failure_is_safe_json(self):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            self.skipTest('Требуется web extra')
        from pathlib import Path
        from unittest.mock import patch
        from research_assistant.server_settings import ServerSettings
        from research_assistant.web.app import create_app
        from research_assistant.user_memory import MemoryError
        with tempfile.TemporaryDirectory() as root:
            settings = ServerSettings('demo', Path(root), 'http://127.0.0.1:2025')
            with patch('research_assistant.web.service.WebService.memory', side_effect=MemoryError('PRIVATE_SQL')):
                with TestClient(create_app(settings)) as client:
                    response = client.get('/api/memory?user_id=alice')
                    self.assertEqual(response.status_code, 400)
                    self.assertNotIn('PRIVATE_SQL', response.text)
                    self.assertIn('error', response.json())
                    invalid = client.post('/api/ask?user_id=alice', json={
                        'request_id': 'invalid-input-test', 'thread_id': 123, 'question': 'Question'})
                    self.assertEqual(invalid.status_code, 400)
