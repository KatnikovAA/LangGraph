import unittest
from research_assistant.chat import validate_materials
from research_assistant.interview.materials import interview_materials


class MaterialsTests(unittest.TestCase):
    def test_empty_interview_explicit_adapter(self):
        values = dict(workflow={'version': 'web-1', 'mode': 'interview'}, status='completed',
                      transcript=[{'round': 1}, {'round': 2}], report_markdown='# Report', sources=[])
        result = interview_materials(values, 'thread')
        self.assertEqual(result['sources'], [])
        with self.assertRaises(ValueError):
            interview_materials({**values, 'status': 'interviewing'}, 'thread')
        with self.assertRaises(ValueError):
            interview_materials({**values, 'workflow': {'mode': 'research'}}, 'thread')
        with self.assertRaises(Exception):
            validate_materials(result)

    def test_unknown_source_ids_rejected(self):
        from research_assistant.interview.sources import validate_source_ids
        with self.assertRaises(ValueError):
            validate_source_ids(['S1'], [])
