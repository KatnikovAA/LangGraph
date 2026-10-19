import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from plan_fixture import valid_plan
from research_assistant.graph import build_graph


class PlanningTests(unittest.TestCase):
    def test_generator_receives_normalized_topic(self):
        received = []

        def generate(topic):
            received.append(topic)
            return valid_plan()

        result = build_graph(generate).invoke({'topic': '  Тема\tPython\n '})
        self.assertEqual(received, ['Тема Python'])
        self.assertEqual(result['topic'], '  Тема\tPython\n ')
        self.assertEqual(result['status'], 'planned')
        self.assertEqual(result['plan'], valid_plan())
        json.dumps(result, ensure_ascii=False)

    def test_empty_topic_does_not_call_generator(self):
        def forbidden(topic):
            self.fail('Генератор не должен вызываться для пустой темы')

        with self.assertRaises(ValueError):
            build_graph(forbidden).invoke({'topic': ' \t\n '})

    def test_invalid_plans_are_rejected(self):
        from research_assistant.planning import PlanGenerationError
        invalid = [None, {}, {'title': ' ', 'sections': []}]
        for target in ('title', 'section', 'question'):
            plan = valid_plan()
            if target == 'title':
                plan['title'] = ' \t '
            elif target == 'section':
                plan['sections'][0]['title'] = ' \n '
            else:
                plan['sections'][0]['questions'][0] = ' \t '
            invalid.append(plan)
        for plan in invalid:
            with self.subTest(plan=plan), self.assertRaises(PlanGenerationError):
                build_graph(lambda topic: plan).invoke({'topic': 'Python'})

    def test_schema_strips_strings_and_accepts_boundaries(self):
        from research_assistant.schemas import ResearchPlan
        for sections in (1, 3, 5):
            for questions in (1, 2, 4):
                plan = {'title': ' План ', 'sections': [
                    {'title': ' Раздел ', 'questions': [' Вопрос? '] * questions}
                    for _ in range(sections)
                ]}
                result = ResearchPlan.model_validate(plan).model_dump(mode='json')
                self.assertEqual(result['title'], 'План')
                self.assertEqual(result['sections'][0]['title'], 'Раздел')
                self.assertEqual(result['sections'][0]['questions'], ['Вопрос?'] * questions)

    def test_size_is_not_rejected_programmatically(self):
        from research_assistant.schemas import ResearchPlan
        plan = valid_plan()
        plan['sections'][0]['questions'][0] = ' '.join(['Слово'] * 81)
        self.assertEqual(ResearchPlan.model_validate(plan).model_dump(mode='json'), plan)

    def test_generation_error_has_no_success_output(self):
        from research_assistant.cli import main
        from research_assistant.planning import PlanGenerationError
        out, err = StringIO(), StringIO()
        with patch('research_assistant.graph.generate_research_plan', side_effect=PlanGenerationError('Ошибка генерации')):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(['--topic', 'Python'])
        self.assertNotEqual(code, 0)
        self.assertEqual(out.getvalue(), '')
        self.assertIn('Ошибка генерации', err.getvalue())

    def test_missing_configuration_and_empty_topic_priority(self):
        from research_assistant.cli import main
        with patch.dict(os.environ, {}, clear=True), patch('research_assistant.planning.load_dotenv'):
            for topic, expected in [('Python', 'POLZA_API_KEY'), ('   ', 'Тема исследования')]:
                out, err = StringIO(), StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = main(['--topic', topic])
                self.assertNotEqual(code, 0)
                self.assertEqual(out.getvalue(), '')
                self.assertIn(expected, err.getvalue())
                self.assertNotIn('Traceback', err.getvalue())

    def test_unexpected_error_is_not_hidden(self):
        from research_assistant.cli import main
        with patch('research_assistant.graph.generate_research_plan', side_effect=RuntimeError('bug')):
            with self.assertRaisesRegex(RuntimeError, 'bug'):
                main(['--topic', 'Python'])
