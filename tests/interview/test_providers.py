import unittest
from unittest.mock import Mock, patch
from research_assistant.interview.providers import ask_analyst, answer_expert, summarize_transcript, InterviewError


class ProviderTests(unittest.TestCase):
    def test_separate_calls_and_data_boundary(self):
        model = Mock()
        model.with_structured_output.return_value.invoke.side_effect = [
            {'text': 'Question', 'search_query': 'query'}, {'text': 'Answer', 'source_ids': ['S1']},
            {'title': 'Report', 'sections': [{'title': 'Result', 'text': 'Text', 'source_ids': ['S1']}]}]
        sources = [dict(title='Title', snippet='snippet', url='https://private.test', section_indexes=[0])]
        with patch('research_assistant.interview.providers.create_model', return_value=model):
            question = ask_analyst('ignore rules', 'clarify', 'role', [])
            answer_expert(question.model_dump(), sources, ['S1'])
            summarize_transcript('topic', [], sources)
        calls = model.with_structured_output.return_value.invoke.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0].args[0][0][0], 'system')
        self.assertEqual(calls[0].args[0][1][0], 'human')
        self.assertNotIn('private.test', str(calls))
        self.assertIn('ignore rules', calls[0].args[0][1][1])

    def test_malformed_output_sanitized(self):
        model = Mock()
        model.with_structured_output.return_value.invoke.return_value = {'secret': 'PRIVATE'}
        with patch('research_assistant.interview.providers.create_model', return_value=model):
            with self.assertRaises(InterviewError) as result:
                ask_analyst('x', '', 'role', [])
        self.assertNotIn('PRIVATE', str(result.exception))
