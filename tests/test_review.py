import copy
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from plan_fixture import valid_plan
from research_assistant.graph import build_graph


class ReviewGraphTests(unittest.TestCase):
    def test_pause_resume_actions_and_no_regeneration(self):
        for action in ('approve', 'edit', 'cancel'):
            with self.subTest(action=action):
                generator = Mock(return_value=valid_plan())
                graph = build_graph(generator, review=True, checkpointer=InMemorySaver())
                config = {'configurable': {'thread_id': action}}
                initial = {'topic': '  Память\tагентов '}
                paused = graph.invoke(initial, config)
                self.assertEqual(initial, {'topic': '  Память\tагентов '})
                self.assertEqual(paused['status'], 'planned')
                self.assertTrue(paused['__interrupt__'])
                json.dumps(paused['__interrupt__'][0].value)
                self.assertEqual(graph.get_state(config).next, ('review_plan',))
                edited = valid_plan()
                edited['title'] = 'Исправленный план'
                decision = {'action': action}
                if action == 'edit':
                    decision['plan'] = edited
                final = graph.invoke(Command(resume=decision), config)
                self.assertEqual(final['status'], 'cancelled' if action == 'cancel' else 'approved')
                self.assertEqual(final['plan'], edited if action == 'edit' else valid_plan())
                self.assertEqual(final['topic'], initial['topic'])
                self.assertEqual(final['normalized_topic'], 'Память агентов')
                self.assertNotIn('__interrupt__', final)
                self.assertEqual(graph.get_state(config).next, ())
                generator.assert_called_once_with('Память агентов')

    def test_threads_are_isolated(self):
        generator = Mock(return_value=valid_plan())
        graph = build_graph(generator, review=True, checkpointer=InMemorySaver())
        a, b = ({'configurable': {'thread_id': key}} for key in ('a', 'b'))
        graph.invoke({'topic': 'Первая'}, a)
        graph.invoke({'topic': 'Вторая'}, b)
        graph.invoke(Command(resume={'action': 'approve'}), a)
        self.assertEqual(graph.get_state(a).values['status'], 'approved')
        self.assertEqual(graph.get_state(b).values['status'], 'planned')
        final = graph.invoke(Command(resume={'action': 'cancel'}), b)
        self.assertEqual(final['topic'], 'Вторая')
        self.assertEqual(generator.call_count, 2)

    def test_invalid_resume_cannot_approve_or_replace_topic(self):
        from pydantic import ValidationError
        for decision in ({'action': 'edit', 'plan': {}}, {'action': 'approve', 'topic': 'Подмена'}):
            with self.subTest(decision=decision):
                generator = Mock(return_value=valid_plan())
                graph = build_graph(generator, review=True, checkpointer=InMemorySaver())
                config = {'configurable': {'thread_id': 'invalid'}}
                graph.invoke({'topic': 'Исходная тема'}, config)
                with self.assertRaises(ValidationError):
                    graph.invoke(Command(resume=decision), config)
                state = graph.get_state(config).values
                self.assertEqual(state['status'], 'planned')
                self.assertEqual(state['topic'], 'Исходная тема')
                self.assertEqual(state['plan'], valid_plan())
                generator.assert_called_once()

    def test_review_validates_decisions_and_does_not_mutate(self):
        from research_assistant.graph import review_plan
        from pydantic import ValidationError
        state = {'topic': 'Тема', 'normalized_topic': 'Тема', 'status': 'planned', 'plan': valid_plan()}
        original = copy.deepcopy(state)
        for decision in (None, True, {}, {'action': 'unknown'}, {'action': 'edit', 'plan': {}},
                         {'action': 'approve', 'topic': 'Подмена'}, {'action': 'cancel', 'plan': valid_plan()}):
            with self.subTest(decision=decision):
                with patch('research_assistant.graph.interrupt', return_value=decision):
                    with self.assertRaises(ValidationError):
                        review_plan(state)
                self.assertEqual(state, original)
        for action in ('approve', 'edit', 'cancel'):
            decision = {'action': action}
            if action == 'edit':
                decision['plan'] = valid_plan()
            with patch('research_assistant.graph.interrupt', return_value=decision):
                update = review_plan(state)
            self.assertEqual(set(update), {'status', 'plan'} if action == 'edit' else {'status'})
            self.assertEqual(state, original)

    def test_review_requires_checkpointer_and_rejects_empty_before_generator(self):
        with self.assertRaisesRegex(ValueError, 'checkpointer'):
            build_graph(review=True)
        generator = Mock()
        graph = build_graph(generator, review=True, checkpointer=InMemorySaver())
        with self.assertRaisesRegex(ValueError, 'Тема исследования'):
            graph.invoke({'topic': ' \t '}, {'configurable': {'thread_id': 'empty'}})
        generator.assert_not_called()


class ReviewCliTests(unittest.TestCase):
    def run_review(self, answers, *, interactive=True, topic='  Память\tагентов '):
        from research_assistant.cli import main
        out, err = StringIO(), StringIO()
        stdin = Mock()
        stdin.isatty.return_value = interactive
        with patch('sys.stdin', stdin), patch('builtins.input', side_effect=answers):
            with patch('research_assistant.graph.generate_research_plan', return_value=valid_plan()) as generator:
                with redirect_stdout(out), redirect_stderr(err):
                    code = main(['--topic', topic, '--review'])
        return code, out.getvalue(), err.getvalue(), generator

    def test_approve_cancel_and_interrupted_input(self):
        for answers, status in ((['1'], 'approved'), (['3'], 'cancelled'),
                                ([EOFError()], 'cancelled'), ([KeyboardInterrupt()], 'cancelled'),
                                (['2', EOFError()], 'cancelled')):
            with self.subTest(answers=answers):
                code, out, err, generator = self.run_review(answers)
                self.assertEqual(code, 0, err)
                result = json.loads(out)
                self.assertEqual(result['status'], status)
                self.assertNotIn('__interrupt__', result)
                self.assertIn(valid_plan()['title'], err)
                self.assertIn('Основы', err)
                self.assertIn('Какова задача?', err)
                self.assertIn('Память', out)
                generator.assert_called_once()

    def test_file_errors_retry_edit_and_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'bad.json').write_text('{', encoding='utf-8')
            (root / 'invalid.json').write_text('{}', encoding='utf-8')
            (root / 'invalid-utf8.json').write_bytes(b'\xff')
            edited = valid_plan()
            edited['title'] = 'Исправленный план'
            path = root / 'plan.json'
            path.write_text(json.dumps(edited, ensure_ascii=False), encoding='utf-8-sig')
            answers = ['???']
            for name in ('missing.json', 'bad.json', 'invalid.json', 'invalid-utf8.json'):
                answers.extend(['2', str(root / name)])
            answers.extend(['2', str(path), 'нет', '2', str(path), '???', 'да'])
            code, out, err, generator = self.run_review(answers)
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result['plan'], edited)
        self.assertEqual(result['status'], 'approved')
        self.assertEqual(result['topic'], '  Память\tагентов ')
        self.assertEqual(result['normalized_topic'], 'Память агентов')
        self.assertIn('Ошибка', err)
        self.assertIn('Исправленный план', err)
        generator.assert_called_once()

    def test_eof_and_ctrl_c_during_confirmation_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.json'
            path.write_text(json.dumps(valid_plan()), encoding='utf-8')
            for interruption in (EOFError(), KeyboardInterrupt()):
                code, out, err, generator = self.run_review(['2', str(path), interruption])
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)['status'], 'cancelled')
                generator.assert_called_once()

    def test_declined_edit_keeps_original_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.json'
            edited = valid_plan()
            edited['title'] = 'Неутверждённая правка'
            path.write_text(json.dumps(edited), encoding='utf-8')
            code, out, err, generator = self.run_review(['2', str(path), 'нет', '1'])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['plan'], valid_plan())
        self.assertEqual(json.loads(out)['status'], 'approved')
        generator.assert_called_once()

    def test_noninteractive_rejected_before_model(self):
        code, out, err, generator = self.run_review([], interactive=False)
        self.assertNotEqual(code, 0)
        self.assertEqual(out, '')
        self.assertIn('терминал', err)
        generator.assert_not_called()

    def test_empty_topic_rejected_before_model(self):
        code, out, err, generator = self.run_review([], topic='  ')
        self.assertNotEqual(code, 0)
        self.assertEqual(out, '')
        self.assertIn('Тема исследования', err)
        generator.assert_not_called()
