"""Publication policy catches sensitive files without exposing their contents."""

import unittest

from scripts.check_repository_security import inspect_file


class RepositorySecurityTests(unittest.TestCase):
    def test_environment_files_and_private_keys_are_rejected(self):
        for name in ('.env', '.env.live', 'config/.env.production', 'credentials.key', 'server.pem'):
            with self.subTest(name=name):
                self.assertTrue(inspect_file(name, ''))

    def test_templates_require_empty_provider_keys(self):
        self.assertEqual(inspect_file('.env.example', 'POLZA_API_KEY=\nTAVILY_API_KEY=\n'), [])
        self.assertTrue(inspect_file('.env.web.example', 'POLZA_API_KEY=unexpected-value\n'))

    def test_tokens_and_private_key_headers_are_rejected_without_echo(self):
        samples = ['sk-' + 'a' * 48, 'tvly-' + 'b' * 48, 'ghp_' + 'c' * 40,
                   '-----BEGIN ' + 'PRIVATE KEY-----']
        for secret in samples:
            with self.subTest(prefix=secret[:4]):
                findings = inspect_file('source.py', secret)
                self.assertTrue(findings)
                self.assertNotIn(secret, repr(findings))

    def test_code_and_obvious_test_credentials_are_allowed(self):
        self.assertEqual(inspect_file('tests/provider.py', "api_key='test-key'"), [])
        self.assertEqual(inspect_file('app.py', "os.getenv('POLZA_API_KEY')"), [])


if __name__ == '__main__':
    unittest.main()
