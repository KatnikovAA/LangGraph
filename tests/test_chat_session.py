import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from research_assistant.graph import build_graph
from research_assistant.persistence import open_saver, workflow_settings
from test_chat import FakeModel
from test_reporting import plan, hits, draft


def completed_research(db, root):
    config = {'configurable': {'thread_id': 'research'}}
    with open_saver(db) as saver:
        graph = build_graph(lambda t: plan(), review=True, search=True, report=True, output_dir=root,
                            checkpointer=saver, search_function=lambda q: hits(), report_generator=lambda *a: draft())
        graph.invoke({'topic': 'Тема', 'workflow': workflow_settings(db, root, 'research')}, config, durability='sync')
        return graph.invoke(Command(resume={'action': 'approve'}), config, durability='sync')


class ChatSessionTests(unittest.TestCase):
    def run_cli(self, args, model):
        from research_assistant.cli import main
        out, err = StringIO(), StringIO()
        with patch('research_assistant.chat.create_model', return_value=model), redirect_stdout(out), redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_create_continue_isolation_and_never_rerun_research(self):
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            original = completed_research(db, root)
            with patch('research_assistant.graph.generate_research_plan', side_effect=AssertionError('Plan rerun')), \
                 patch('research_assistant.graph.search_web', side_effect=AssertionError('Search rerun')), \
                 patch('research_assistant.graph.generate_report_draft', side_effect=AssertionError('Report rerun')), \
                 patch('research_assistant.graph.write_report', side_effect=AssertionError('Write rerun')):
                model = FakeModel([AIMessage('Ответ 1'), AIMessage('Ответ 2'), AIMessage('Другой диалог')])
                code, out, err = self.run_cli(['--discuss', 'research', '--question', 'Первый вопрос', '--checkpoint-db', db], model)
                self.assertEqual(code, 0, err)
                first = json.loads(out)
                chat_id = first['chat_thread_id']
                self.assertNotEqual(chat_id, 'research')
                self.assertEqual(first['research_thread_id'], 'research')
                code, out, err = self.run_cli(['--chat', chat_id, '--question', 'Второй вопрос', '--checkpoint-db', db], model)
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)['answer'], 'Ответ 2')
                self.assertEqual([m.content for m in model.contexts[1][1:]], ['Первый вопрос', 'Ответ 1', 'Второй вопрос'])
                code, out, err = self.run_cli(['--discuss', 'research', '--question', 'Отдельный вопрос', '--checkpoint-db', db], model)
                self.assertEqual(code, 0, err)
                self.assertNotEqual(json.loads(out)['chat_thread_id'], chat_id)
                self.assertEqual(len(model.contexts[2]), 2)
                self.assertEqual(Path(original['report_path']).read_text(encoding='utf-8'), original['report_markdown'])

    def test_invalid_threads_bindings_flags_and_empty_question_no_model(self):
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            completed_research(db, root)
            cases = [ ['--discuss', 'unknown', '--question', 'Q'], ['--chat', 'unknown', '--question', 'Q'],
                      ['--chat', 'research', '--question', 'Q'], ['--discuss', 'research', '--question', '  '],
                      ['--discuss', 'research', '--question', 'Q', '--review'],
                      ['--chat', 'x', '--question', 'Q', '--topic', 'new'], ['--question', 'Q'] ]
            for flags in cases:
                with self.subTest(flags=flags):
                    model = Mock(side_effect=AssertionError('API'))
                    code, out, err = self.run_cli(flags + ['--checkpoint-db', db], model)
                    self.assertEqual(code, 2)
                    self.assertEqual(out, '')
                    self.assertIn('Ошибка', err)
                    model.bind_tools.assert_not_called()
            # Non-completed research is not eligible.
            with open_saver(db) as saver:
                graph = build_graph(lambda t: plan(), review=True, search=True, report=True, checkpointer=saver)
                config = {'configurable': {'thread_id': 'research'}}
                graph.update_state(config, {'status': 'no_sources'})
            code, out, err = self.run_cli(['--discuss', 'research', '--question', 'Q', '--checkpoint-db', db], Mock())
            self.assertEqual(code, 2)
            self.assertEqual(out, '')

    def test_model_error_retry_sanitized_and_no_duplicate_human(self):
        import httpx
        from openai import BadRequestError
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            completed_research(db, root)
            error = BadRequestError('secret-api-key', response=httpx.Response(400, request=httpx.Request('POST', 'https://example.org')),
                                    body={'secret': 'secret-api-key'})
            code, out, err = self.run_cli(['--discuss', 'research', '--question', 'Q', '--checkpoint-db', db], FakeModel([error]))
            self.assertEqual(code, 2)
            self.assertEqual(out, '')
            self.assertNotIn('secret-api-key', err)
            self.assertIn('Tool Calling', err)
            chat_id = err.split('Chat Thread: ')[1].splitlines()[0]
            code, out, err = self.run_cli(['--chat', chat_id, '--question', 'Другой', '--checkpoint-db', db], Mock())
            self.assertEqual(code, 2)
            model = FakeModel([AIMessage('Готово')])
            code, out, err = self.run_cli(['--chat', chat_id, '--checkpoint-db', db], model)
            self.assertEqual(code, 0, err)
            self.assertEqual(sum(isinstance(m, HumanMessage) for m in model.contexts[0]), 1)
            self.assertNotIn(b'secret-api-key', Path(db).read_bytes())

    def test_new_process_recovers_history(self):
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            completed_research(db, root)
            worker = str(Path(__file__).with_name('chat_worker.py'))
            def run(mode):
                result = subprocess.run([sys.executable, worker, mode, db], capture_output=True, text=True,
                                        encoding='utf-8', timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            first = run('create')
            second = run('continue')
            self.assertEqual(first['chat_thread_id'], second['chat_thread_id'])
            self.assertEqual(second['answer'], 'История восстановлена')

    def test_chat_version_mode_binding_and_materials_checked_before_api(self):
        from research_assistant.chat import build_chat_graph
        with tempfile.TemporaryDirectory() as root:
            db = str(Path(root) / 'db.sqlite')
            completed_research(db, root)
            code, out, err = self.run_cli(['--discuss', 'research', '--question', 'Q', '--checkpoint-db', db], FakeModel([AIMessage('A')]))
            self.assertEqual(code, 0, err)
            chat_id = json.loads(out)['chat_thread_id']
            config = {'configurable': {'thread_id': chat_id}}
            with open_saver(db) as saver:
                graph = build_chat_graph(checkpointer=saver)
                original = graph.get_state(config).values
                for field, value in [('version', 999), ('mode', 'research'), ('thread_id', 'other'),
                                     ('research_thread_id', 'other'), ('checkpoint_db', 'other')]:
                    graph.update_state(config, {'chat_settings': {**original['chat_settings'], field: value}}, as_node='finish')
                    model = Mock()
                    code, out, err = self.run_cli(['--chat', chat_id, '--question', 'Q', '--checkpoint-db', db], model)
                    self.assertEqual(code, 2)
                    self.assertEqual(out, '')
                    model.bind_tools.assert_not_called()
                graph.update_state(config, {'chat_settings': original['chat_settings'], 'report_markdown': 'Подменённый отчёт'}, as_node='finish')
                model = Mock()
                code, out, err = self.run_cli(['--chat', chat_id, '--question', 'Q', '--checkpoint-db', db], model)
                self.assertEqual(code, 2)
                self.assertIn('не совпадают', err)
                model.bind_tools.assert_not_called()
