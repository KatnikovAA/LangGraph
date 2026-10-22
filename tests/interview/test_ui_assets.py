import re
import unittest
from pathlib import Path


class UIAssetTests(unittest.TestCase):
    def test_assets_and_labels(self):
        root = Path(__file__).resolve().parents[2]
        html = (root / 'research_assistant/web/static/index.html').read_text(encoding='utf-8')
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))
        for identifier in ['research-mode', 'clarification', 'interview-panel', 'interview-progress', 'interview-transcript', 'interview-resume']:
            self.assertIn(identifier, ids)
        for asset in ['interview.js', 'interview.css']:
            self.assertIn('/interview-static/' + asset, html)
            self.assertTrue((root / 'research_assistant/interview/static' / asset).is_file())
