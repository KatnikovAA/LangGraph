import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ServerLifecycleTests(unittest.TestCase):
    def test_custom_store_reopens_and_is_separate(self):
        from research_assistant.server_store import create_store
        from research_assistant.server_settings import load_server_settings
        from research_assistant.user_memory import store_identity
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'RA_WEB_DATA': root, 'RA_WEB_MODE': 'demo'}):
            settings = load_server_settings()
            with create_store() as store:
                identity = store_identity(store)
                store.put(('alice', 'notes'), 'one', {'text': 'persistent'})
            with create_store() as store:
                self.assertEqual(store_identity(store), identity)
                self.assertEqual(store.get(('alice', 'notes'), 'one').value['text'], 'persistent')
            self.assertEqual(settings.mode, 'demo')

    def test_server_chat_without_cli_saver(self):
        from research_assistant.chat import build_chat_graph
        graph = build_chat_graph(persistence='server')
        self.assertIsNone(graph.checkpointer)

    def test_unknown_mode_rejected(self):
        from research_assistant.server_settings import load_server_settings
        with patch.dict(os.environ, {'RA_WEB_MODE': 'auto'}):
            with self.assertRaises(ValueError):
                load_server_settings()

    def test_corrupt_files_stop_real_agent_server_before_native_load(self):
        import importlib.util
        if importlib.util.find_spec('langgraph_api') is None:
            self.skipTest('Требуется web extra')
        import pickle
        import socket
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as root:
            runtime = Path(root)/'runtime'/'.langgraph_api'; runtime.mkdir(parents=True)
            broken = runtime/'.langgraph_ops.pckl'; broken.write_bytes(b'BROKEN-PERSISTENCE')
            counter = runtime/'.langgraph_retry_counter.pckl'; counter.write_bytes(pickle.dumps({}))
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
            env = {**os.environ, 'RA_WEB_DATA': root, 'RA_WEB_MODE': 'demo',
                   'RA_AGENT_URL': f'http://127.0.0.1:{port}', 'PYTHONUTF8': '1'}
            result = subprocess.run([sys.executable, '-m', 'research_assistant.web.agent'], env=env,
                                    capture_output=True, timeout=60)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(broken.read_bytes(), b'BROKEN-PERSISTENCE')
            self.assertEqual(counter.read_bytes(), pickle.dumps({}))
