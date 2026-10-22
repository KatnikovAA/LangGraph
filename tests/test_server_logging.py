import logging
import unittest


class ServerLogTests(unittest.TestCase):
    def test_raw_provider_error_and_traceback_are_not_logged(self):
        from research_assistant.server_logging import SafeServerLogs
        record = logging.LogRecord('server', logging.ERROR, '', 1,
            {'event': 'provider SECRET_RESPONSE', 'error': 'SECRET_RESPONSE', 'input': 'PRIVATE', 'run_id': 'safe-id'}, (),
            (ValueError, ValueError('SECRET_RESPONSE'), None))
        self.assertTrue(SafeServerLogs().filter(record))
        self.assertNotIn('SECRET_RESPONSE', str(record.msg))
        self.assertNotIn('PRIVATE', str(record.msg))
        self.assertIsNone(record.exc_info)
        self.assertEqual(record.msg['run_id'], 'safe-id')
