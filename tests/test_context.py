import unittest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from research_assistant.chat_context import ContextBudget, filter_history, trim_history, estimate_tokens
from research_assistant.chat import ChatError


class ContextTests(unittest.TestCase):
    def test_filter_and_trim_keep_whole_tool_turns(self):
        messages = [HumanMessage('old', id='h1'), AIMessage('', id='a1', tool_calls=[
            {'id': 'c', 'name': 'get_source', 'args': {'source_id': 'S1'}}]),
            ToolMessage('data', tool_call_id='c', id='t1'), AIMessage('done', id='a2'),
            HumanMessage('current', id='h2')]
        self.assertEqual(filter_history(messages, 'a2'), messages[4:])
        self.assertEqual(trim_history(messages, estimate_tokens(messages[4:])), messages[4:])
        self.assertEqual(trim_history(messages, 10000), messages)
        with self.assertRaises(ChatError):
            filter_history(messages, 't1')
        with self.assertRaises(ChatError):
            trim_history(messages, 1)

    def test_budget_validation(self):
        with self.assertRaises(ChatError):
            ContextBudget(input_tokens=100, answer_reserve=100)

    def test_summary_provider_sanitizes_error_and_reuses_config(self):
        from unittest.mock import patch
        from research_assistant.chat_context import summarize_with_model
        from test_chat import FakeModel
        import httpx
        from openai import BadRequestError
        error = BadRequestError('PRIVATE_KEY', response=httpx.Response(400,
            request=httpx.Request('POST', 'https://example.org')), body={'secret': 'PRIVATE_KEY'})
        for response in [error, AIMessage(''), AIMessage('Краткое Summary')]:
            model = FakeModel([response])
            with patch('research_assistant.chat_context.create_model', return_value=model):
                if isinstance(response, Exception) or not response.content:
                    with self.assertRaises(ChatError) as caught:
                        summarize_with_model([HumanMessage('Данные')], {'tags': ['summary']})
                    self.assertNotIn('PRIVATE_KEY', str(caught.exception))
                else:
                    self.assertEqual(summarize_with_model([HumanMessage('Данные')], {'tags': ['summary']}),
                                     'Краткое Summary')
                self.assertEqual(len(model.contexts), 1)
