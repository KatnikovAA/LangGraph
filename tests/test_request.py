import json
import subprocess
import sys
import unittest


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, '-m', 'research_assistant', *args],
            capture_output=True, text=True, encoding='utf-8',
        )

    def test_success(self):
        topic = '  Техническая\tтема\n исследования  '
        result = self.run_cli('--topic', topic)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            'topic': topic, 'normalized_topic': 'Техническая тема исследования',
            'status': 'ready',
        })
        self.assertIn('Техническая', result.stdout)
        self.assertEqual(result.stderr, '')

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
        graph = build_graph()
        for topic, normalized in (
            ('LangGraph', 'LangGraph'),
            ('  Тема\t исследования\nPython  ', 'Тема исследования Python'),
            ('\u00a0Тема\u2003Python\u00a0', 'Тема Python'),
        ):
            with self.subTest(topic=topic):
                state = {'topic': topic}
                self.assertEqual(graph.invoke(state), {
                    'topic': topic, 'normalized_topic': normalized, 'status': 'ready',
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
