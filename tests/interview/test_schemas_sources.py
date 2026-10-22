import unittest
from research_assistant.interview.schemas import validate_interview_input, InterviewQuestion
from research_assistant.interview.sources import merge_sources, validate_source_ids


class SchemaSourceTests(unittest.TestCase):
    def test_invalid_input(self):
        for args in [('', ''), ('topic', None), (12, '')]:
            with self.assertRaises(ValueError):
                validate_interview_input(*args)
        self.assertEqual(validate_interview_input(' a  b ', '')['topic'], 'a b')
        with self.assertRaises(ValueError):
            InterviewQuestion(text='x', search_query='x', url='https://invented.test')

    def test_registry_stability(self):
        def source(url):
            return dict(title=url, url='https://example.test/' + url, snippet='snippet')
        first, ids = merge_sources([], [source('a'), source('b')], 1)
        second, next_ids = merge_sources(first, [source('b'), source('c')], 2)
        self.assertEqual(ids, ['S1', 'S2'])
        self.assertEqual(next_ids, ['S2', 'S3'])
        self.assertEqual(second[1]['section_indexes'], [0, 1])
        self.assertEqual(first[1]['section_indexes'], [0])
        third, new_ids = merge_sources(second, [source('a/')], 2)
        self.assertEqual(new_ids, ['S4'])
        self.assertEqual(len(third), 4)

    def test_empty_then_nonempty_and_ids(self):
        self.assertEqual(merge_sources([], [], 1), ([], []))
        with self.assertRaises(ValueError):
            validate_source_ids(['S999'], ['S1'])
        self.assertEqual(validate_source_ids(['S1', 'S1'], ['S1']), ['S1'])
