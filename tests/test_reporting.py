import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from research_assistant.graph import build_graph
from research_assistant.reporting import ReportError, render_report, write_report


def plan():
    return {'title': 'План', 'sections': [{'title': 'Основы', 'questions': ['Что известно?']}]}


def hits():
    return [{'title': 'Документация', 'url': 'https://example.org/docs', 'snippet': 'Краткие данные'}]


def draft():
    return {'title': 'Обзор', 'sections': [{'title': 'Результат', 'text': 'Краткий результат.', 'source_ids': ['S1']}]}


class ReportingTests(unittest.TestCase):
    def test_reference_validation_and_rendering(self):
        markdown = render_report(draft(), hits())
        self.assertIn('[S1]: <https://example.org/docs>', markdown)
        self.assertIn('- [S1 — Документация][S1]', markdown)
        self.assertIn('snippets Search API', markdown)
        invalid = draft()
        invalid['sections'][0]['source_ids'] = ['S2']
        with self.assertRaises(ReportError):
            render_report(invalid, hits())

    def test_model_cannot_add_markdown_links_or_raw_urls(self):
        data = draft()
        data['sections'][0]['text'] = '[Ложная ссылка](https://invented.example) <https://invented.example>'
        sources = hits()
        sources[0]['url'] += '?q=a b'
        sources[0]['title'] = 'Источник\n[S9]: <https://invented.example>'
        markdown = render_report(data, sources)
        self.assertNotIn('https://invented.example', markdown)
        self.assertIn('<https://example.org/docs?q=a%20b>', markdown)
        self.assertNotIn('\n[S9]:', markdown)

    def test_atomic_utf8_idempotent_safe_filename_and_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            path = write_report('Привет', root, '../../unsafe')
            self.assertTrue(Path(path).parent.samefile(root))
            self.assertEqual(Path(path).read_text(encoding='utf-8'), 'Привет')
            self.assertEqual(write_report('Обновлено', root, '../../unsafe'), path)
            with patch('research_assistant.reporting.os.replace', side_effect=PermissionError()):
                with self.assertRaises(ReportError):
                    write_report('Ошибка', root, '../../unsafe')
            self.assertEqual(Path(path).read_text(encoding='utf-8'), 'Обновлено')
            self.assertEqual(len(list(Path(root).iterdir())), 1)

    def test_report_graph_branches_edit_and_partial_updates(self):
        with tempfile.TemporaryDirectory() as root:
            for action, found in [('approve', True), ('edit', True), ('cancel', True), ('approve', False)]:
                with self.subTest(action=action, found=found):
                    generator = Mock(return_value=draft())
                    searcher = Mock(return_value=hits() if found else [])
                    graph = build_graph(lambda topic: plan(), review=True, search=True, report=True,
                                        output_dir=root, checkpointer=InMemorySaver(),
                                        search_function=searcher, report_generator=generator)
                    config = {'configurable': {'thread_id': f'{action}-{found}'}}
                    graph.invoke({'topic': ' Тема '}, config)
                    decision = {'action': action}
                    edited = plan()
                    edited['title'] = 'Исправлено'
                    if action == 'edit':
                        decision['plan'] = edited
                    result = graph.invoke(Command(resume=decision), config)
                    if action == 'cancel' or not found:
                        generator.assert_not_called()
                        self.assertNotIn('report_path', result)
                        self.assertEqual(result['status'], 'cancelled' if action == 'cancel' else 'no_sources')
                    else:
                        self.assertEqual(result['status'], 'completed')
                        self.assertTrue(Path(result['report_path']).is_file())
                        args = generator.call_args.args
                        self.assertEqual(args[1], edited if action == 'edit' else plan())
                        self.assertEqual(args[2], [{'id': 'S1', 'title': 'Документация', 'snippet': 'Краткие данные'}])

    def test_failed_generation_never_completes(self):
        with tempfile.TemporaryDirectory() as root:
            graph = build_graph(lambda topic: plan(), review=True, search=True, report=True,
                                output_dir=root, checkpointer=InMemorySaver(), search_function=lambda q: hits(),
                                report_generator=Mock(side_effect=ReportError('Не удалось')))
            config = {'configurable': {'thread_id': 'error'}}
            graph.invoke({'topic': 'Тема'}, config)
            with self.assertRaises(ReportError):
                graph.invoke(Command(resume={'action': 'approve'}), config)
            self.assertEqual(graph.get_state(config).values['status'], 'sources_found')
            self.assertEqual(list(Path(root).iterdir()), [])
