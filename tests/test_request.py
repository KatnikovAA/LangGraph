import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

from plan_fixture import valid_plan


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, '-m', 'research_assistant', *args],
            capture_output=True, text=True, encoding='utf-8',
        )

    def test_success(self):
        from research_assistant.cli import main
        topic = '  Техническая\tтема\n исследования  '
        out, err = StringIO(), StringIO()
        with patch('research_assistant.graph.generate_research_plan', return_value=valid_plan()):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(['--topic', topic])
        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(json.loads(out.getvalue()), {
            'topic': topic, 'normalized_topic': 'Техническая тема исследования',
            'status': 'planned', 'plan': valid_plan(),
        })
        self.assertIn('Техническая', out.getvalue())
        self.assertEqual(err.getvalue(), '')

    def test_empty_topic(self):
        for topic in ('', '  \t\n '):
            with self.subTest(topic=topic):
                result = self.run_cli('--topic', topic)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Тема исследования не должна быть пустой', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(result.stdout, '')

    def test_topic_required(self):
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--topic', result.stderr)


class GraphTests(unittest.TestCase):
    def test_graph(self):
        from research_assistant.graph import build_graph
        graph = build_graph(lambda topic: valid_plan())
        for topic, normalized in (
            ('LangGraph', 'LangGraph'),
            ('  Тема\t исследования\nPython  ', 'Тема исследования Python'),
            ('\u00a0Тема\u2003Python\u00a0', 'Тема Python'),
        ):
            with self.subTest(topic=topic):
                state = {'topic': topic}
                self.assertEqual(graph.invoke(state), {
                    'topic': topic, 'normalized_topic': normalized,
                    'status': 'planned', 'plan': valid_plan(),
                })
                self.assertEqual(state, {'topic': topic})

    def test_rejects_empty(self):
        from research_assistant.graph import build_graph
        for topic in ('', ' \t\n '):
            with self.subTest(topic=topic):
                with self.assertRaisesRegex(ValueError, 'Тема исследования'):
                    build_graph().invoke({'topic': topic})

    def test_nodes_return_partial_updates_without_mutation(self):
        from research_assistant.graph import validate_topic, prepare_request
        state = {'topic': ' Тема '}
        self.assertEqual(validate_topic(state), {'normalized_topic': 'Тема'})
        self.assertEqual(prepare_request(state), {'status': 'ready'})
        self.assertEqual(state, {'topic': ' Тема '})


if __name__ == '__main__':
    unittest.main()
