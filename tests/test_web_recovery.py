import json
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import patch


class RecoveryTests(unittest.TestCase):
    def test_corrupt_runtime_is_preserved_before_native_startup(self):
        from research_assistant.web.runtime_guard import guard_runtime
        with tempfile.TemporaryDirectory() as root:
            data = Path(root) / '.langgraph_api'; data.mkdir()
            broken = data / '.langgraph_ops.pckl'; broken.write_bytes(b'corrupt data')
            retry = data / '.langgraph_retry_counter.pckl'; retry.write_bytes(pickle.dumps({}))
            before = {p.name: p.read_bytes() for p in data.iterdir()}
            with self.assertRaises(ValueError):
                guard_runtime(Path(root), versions={'test': '1'})
            self.assertEqual(before, {p.name: p.read_bytes() for p in data.iterdir()})

    def test_version_change_does_not_touch_runtime(self):
        from research_assistant.web.runtime_guard import guard_runtime
        with tempfile.TemporaryDirectory() as root:
            guard_runtime(Path(root), versions={'test': '1'})
            with self.assertRaises(ValueError):
                guard_runtime(Path(root), versions={'test': '2'})
            self.assertEqual(json.loads((Path(root)/'format.json').read_text()), {'test': '1'})

    def test_resume_selects_turn_id_and_any_pending_node(self):
        from research_assistant.web.recovery import pending_checkpoint
        def point(identifier, human_id, next_node):
            return {'checkpoint': {'checkpoint_id': identifier}, 'next': [next_node],
                    'values': {'status': 'answering', 'messages': [{'type': 'human', 'id': human_id, 'content': 'Repeated question'}]}}
        current = point('current', 'new-turn', 'begin_turn')['values']
        history = [point('rejected', 'new-turn', 'begin_turn'), point('input', 'new-turn', '__start__'),
                   point('right', 'new-turn', 'load_memory'), point('old', 'old-turn', 'run_agent')]
        self.assertEqual(pending_checkpoint(history, current), 'right')
        self.assertIsNone(pending_checkpoint(history[3:], current))
