import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
from research_assistant.team.demo import demo_services


class DemoTests(unittest.TestCase):
    def test_resume_factory_does_not_wait_for_completed_a(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'team-fault-used').touch()
            event=Mock();event.wait.return_value=False
            with patch.dict('os.environ',{'RA_WEB_DATA':root,'RA_TEAM_DEMO_FAIL_B':'1','RA_TEAM_DEMO_DELAY':'0'}),patch('threading.Event',return_value=event):
                services=demo_services()
                answer=services['expert']({'text':'Риски: в ответе указано ограничение'},[],[])
            self.assertEqual(answer.source_ids,[])
            event.wait.assert_not_called()
