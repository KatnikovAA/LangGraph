import re
import unittest
from pathlib import Path


class UIAssetsTests(unittest.TestCase):
    def test_team_form_and_assets(self):
        root=Path(__file__).resolve().parents[2]
        html=(root/'research_assistant/web/static/index.html').read_text(encoding='utf-8')
        ids=re.findall(r'\bid="([^"]+)"',html)
        self.assertEqual(len(ids),len(set(ids)))
        for key in ['team-panel','team-review','team-workers','team-status','team-approve','team-cancel','team-resume']:
            self.assertIn(key,ids)
        self.assertIn('Команда аналитиков',html)
        self.assertIn('Одно интервью',html)
        for asset in ['team.js','team.css']:
            self.assertIn('/team-static/'+asset,html)
            self.assertTrue((root/'research_assistant/team/static'/asset).is_file())
