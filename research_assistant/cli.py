"""Terminal interface for preparing a research request."""

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from research_assistant.graph import EmptyTopicError, MAX_CONCURRENCY, build_graph
from research_assistant.planning import ConfigurationError, PlanGenerationError
from research_assistant.schemas import ResearchPlan
from research_assistant.search import SearchError
from research_assistant.reporting import ReportError
from research_assistant.persistence import PersistenceError, open_saver, workflow_settings, inspect_thread
from research_assistant.chat import ChatError
from research_assistant.chat_session import run_chat
from research_assistant.history import research_history, research_checkpoint, describe_snapshot, stop_kind
from research_assistant.time_travel import prepare_branch


def show_plan(plan: dict) -> None:
    print(f"\n{plan['title']}", file=sys.stderr)
    for index, section in enumerate(plan['sections'], 1):
        print(f"{index}. {section['title']}", file=sys.stderr)
        for question in section['questions']:
            print(f"   - {question}", file=sys.stderr)


def read_answer(prompt: str) -> str:
    print(prompt, file=sys.stderr, flush=True)
    return input().strip()


def request_review(plan: dict) -> dict:
    """Keep interaction outside graph nodes and stdout free of prompts."""
    show_plan(plan)
    try:
        while True:
            action = read_answer("1 — утвердить; 2 — загрузить исправленный план; 3 — отменить")
            if action == "1":
                return {"action": "approve"}
            if action == "3":
                return {"action": "cancel"}
            if action != "2":
                print("Ошибка: выберите 1, 2 или 3.", file=sys.stderr)
                continue
            path = read_answer("Путь к UTF-8 JSON-файлу плана:")
            try:
                raw = Path(path).read_text(encoding="utf-8-sig")
                edited = ResearchPlan.model_validate_json(raw).model_dump(mode="json")
            except (OSError, ValueError) as error:
                # ValidationError is a ValueError; do not print file contents.
                if isinstance(error, ValidationError):
                    message = "Файл должен содержать корректный JSON-план с title и sections."
                elif isinstance(error, UnicodeError):
                    message = "Файл должен быть сохранён в UTF-8."
                else:
                    message = "Не удалось прочитать файл плана. Проверьте путь и доступ."
                print(f"Ошибка: {message}", file=sys.stderr)
                continue
            show_plan(edited)
            while True:
                answer = read_answer("Утвердить показанный исправленный план? да / нет")
                if answer.casefold() == "да":
                    return {"action": "edit", "plan": edited}
                if answer.casefold() == "нет":
                    break
                print("Ошибка: введите да или нет.", file=sys.stderr)
    except (EOFError, KeyboardInterrupt):
        print("\nПроверка отменена пользователем.", file=sys.stderr)
        return {"action": "cancel"}


def require_terminal() -> None:
    if sys.stdin is None or not sys.stdin.isatty():
        raise ConfigurationError('--review требует интерактивный терминал для ввода решения.')


def persistent_run(args) -> dict:
    db = str(Path(args.checkpoint_db or '.research_assistant/checkpoints.sqlite').resolve())
    thread_id = args.resume or uuid4().hex
    config = {'configurable': {'thread_id': thread_id}, 'max_concurrency': MAX_CONCURRENCY}
    print(f'Thread: {thread_id}\nCheckpoints: {db}', file=sys.stderr, flush=True)
    with open_saver(db, existing=bool(args.resume)) as saver:
        if args.resume:
            # Inspect before any invocation; no SDK clients are constructed here.
            probe = build_graph(review=True, search=True, report=True, checkpointer=saver)
            checkpoint_id = getattr(args, 'checkpoint_id', None)
            snapshot = (research_checkpoint(probe, thread_id, checkpoint_id, db) if checkpoint_id
                        else inspect_thread(probe, config, db))
            inspect_thread(probe, snapshot.config, db)
            if checkpoint_id and snapshot.next and not snapshot.values['workflow'].get('artifact_id'):
                raise PersistenceError('Исторический Checkpoint сначала подготовьте через --replay или --fork.')
            config = {**snapshot.config, 'max_concurrency': MAX_CONCURRENCY}
            output = snapshot.values['workflow']['output_dir']
            graph = build_graph(review=True, search=True, report=True, output_dir=output, checkpointer=saver,
                                break_before_search=snapshot.values['workflow'].get('break_before_search', False))
            if not snapshot.next:
                result = dict(snapshot.values)
            elif any(task.interrupts for task in snapshot.tasks):
                require_terminal()
                decision = request_review(snapshot.values['plan'])
                result = graph.invoke(Command(resume=decision), config, durability='sync')
            else:
                result = graph.invoke(None, config, durability='sync')
                if result.get('__interrupt__'):
                    config = graph.get_state({'configurable': {'thread_id': thread_id}}).config
                    require_terminal()
                    decision = request_review(result['__interrupt__'][0].value['plan'])
                    result = graph.invoke(Command(resume=decision), config, durability='sync')
        else:
            output = str(Path(args.output_dir or 'reports').resolve())
            if not args.pause_after_plan:
                require_terminal()
            breakpoint = getattr(args, 'break_before_search', False)
            graph = build_graph(review=True, search=True, report=True, output_dir=output, checkpointer=saver,
                                break_before_search=breakpoint)
            result = graph.invoke({'topic': args.topic, 'workflow': workflow_settings(db, output, thread_id,
                                  break_before_search=breakpoint)},
                                  config, durability='sync')
            if not args.pause_after_plan:
                decision = request_review(result['__interrupt__'][0].value['plan'])
                result = graph.invoke(Command(resume=decision), config, durability='sync')
        current = (snapshot if args.resume and not snapshot.next
                   else graph.get_state({'configurable': {'thread_id': thread_id}}))
        paused = bool(current.next)
        return {key: value for key, value in result.items() if key != '__interrupt__'} | {
            'thread_id': thread_id, 'checkpoint_db': db, 'paused': paused,
            'checkpoint_id': current.config['configurable']['checkpoint_id'], 'stop_kind': stop_kind(current)}


def checkpoint_command(args) -> dict:
    db = str(Path(args.checkpoint_db or '.research_assistant/checkpoints.sqlite').resolve())
    thread_id = args.history or args.inspect or args.replay or args.fork
    with open_saver(db, existing=True, read_only=bool(args.history or args.inspect)) as saver:
        graph = build_graph(review=True, search=True, report=True, checkpointer=saver)
        if args.history:
            return {'thread_id': thread_id, 'checkpoints': [describe_snapshot(s) for s in research_history(graph, thread_id, db)]}
        if args.inspect:
            return describe_snapshot(research_checkpoint(graph, thread_id, args.checkpoint_id, db))
        new_plan = None
        if args.fork:
            try:
                new_plan = ResearchPlan.model_validate_json(Path(args.plan_file).read_text(encoding='utf-8-sig')).model_dump(mode='json')
            except (OSError, ValueError) as error:
                raise PersistenceError('Не удалось прочитать корректный UTF-8 JSON Plan: нужны title и sections.') from error
        config = prepare_branch(graph, thread_id, args.checkpoint_id, db,
                                operation='fork' if args.fork else 'replay', new_plan=new_plan)
        return {**describe_snapshot(graph.get_state(config)), 'checkpoint_db': db, 'prepared': True}


def main(argv: list[str] | None = None) -> int:
    # Keep Cyrillic readable when Windows redirects stdout/stderr to pipes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Составление плана исследования")
    parser.add_argument("--topic", help="Тема исследования")
    parser.add_argument("--review", action="store_true", help="Проверить и утвердить план интерактивно")
    parser.add_argument("--search", action="store_true", help="Найти источники после утверждения плана")
    parser.add_argument('--report', action='store_true', help='Создать и сохранить Markdown-отчёт')
    parser.add_argument('--checkpoint-db', help='Файл SQLite (по умолчанию .research_assistant/checkpoints.sqlite)')
    parser.add_argument('--output-dir', help='Каталог отчётов (по умолчанию reports/)')
    parser.add_argument('--pause-after-plan', action='store_true', help='Сохранить Pause без запроса решения')
    parser.add_argument('--resume', metavar='THREAD_ID', help='Продолжить сохранённый полный режим')
    checkpoint_modes = parser.add_mutually_exclusive_group()
    for flag in ('history', 'inspect', 'replay', 'fork'):
        checkpoint_modes.add_argument('--' + flag, metavar='THREAD_ID', help='Research ' + flag)
    parser.add_argument('--checkpoint-id', help='Точный Research Checkpoint для inspect/replay/fork/resume')
    parser.add_argument('--plan-file', help='UTF-8 JSON альтернативного Plan для --fork')
    parser.add_argument('--break-before-search', action='store_true', help='Static Breakpoint перед prepare_search')
    parser.add_argument('--research-checkpoint-id', help='Завершённый Research Checkpoint для нового --discuss')
    parser.add_argument('--discuss', metavar='RESEARCH_ID', help='Создать обсуждение завершённого исследования')
    parser.add_argument('--chat', metavar='CHAT_ID', help='Продолжить отдельный диалог по отчёту')
    parser.add_argument('--question', help='Один вопрос по отчёту')
    parser.add_argument('--stream', action='store_true', help='Прогресс и предварительные фрагменты обсуждения в stderr')
    parser.add_argument('--context-budget', type=int, help='Приблизительный общий бюджет нового Chat (8192)')
    parser.add_argument('--answer-reserve', type=int, help='Резерв ответа в бюджете нового Chat (512)')
    parser.add_argument('--summary-threshold', type=int, help='Порог пересказа истории нового Chat (1600)')
    parser.add_argument('--summary-budget', type=int, help='Приблизительный размер Summary нового Chat (512)')
    parser.add_argument('--recent-turns', type=int, help='Число последних завершённых реплик без пересказа (2)')
    args = parser.parse_args(argv)
    budget_flags = any(getattr(args, key) is not None for key in (
        'context_budget', 'answer_reserve', 'summary_threshold', 'summary_budget', 'recent_turns'))
    if args.history or args.inspect or args.replay or args.fork:
        incompatible = (args.topic is not None or args.resume is not None or args.review or args.search or args.report
            or args.pause_after_plan or args.output_dir is not None or args.discuss is not None or args.chat is not None
            or args.question is not None or args.stream or budget_flags or args.break_before_search
            or args.research_checkpoint_id is not None)
        if (incompatible or (args.history is not None and (args.checkpoint_id is not None or args.plan_file is not None))
                or (args.history is None and not args.checkpoint_id)
                or (args.fork is not None) != (args.plan_file is not None)):
            print('Ошибка: history допускает только THREAD_ID/--checkpoint-db; inspect/replay/fork требуют '
                  '--checkpoint-id, только fork требует --plan-file. Режимы смешивать нельзя.', file=sys.stderr)
            return 2
        try:
            result = checkpoint_command(args)
        except (PersistenceError, ConfigurationError) as error:
            print(f'Ошибка: {error}', file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if (args.plan_file is not None or (args.checkpoint_id is not None and (args.resume is None or not args.checkpoint_id.strip()))
            or (args.research_checkpoint_id is not None and args.discuss is None)
            or (args.research_checkpoint_id is not None and not args.research_checkpoint_id.strip())
            or (args.break_before_search and (not args.report or args.resume is not None))):
        print('Ошибка: checkpoint-id требует resume; plan-file требует fork; research-checkpoint-id требует discuss; '
              'break-before-search задаётся только для нового полного Research.', file=sys.stderr)
        return 2
    if args.discuss is not None or args.chat is not None or args.question is not None or args.stream or budget_flags:
        if ((args.discuss is None and args.chat is None) or (args.discuss is not None and args.chat is not None)
                or (args.discuss is not None and (not args.discuss.strip() or args.question is None))
                or args.topic is not None or args.resume is not None or args.review or args.search
                or args.report or args.pause_after_plan or args.output_dir is not None
                or args.break_before_search
                or (budget_flags and args.discuss is None)):
            print('Ошибка: используйте --discuss RESEARCH_ID --question TEXT либо --chat CHAT_ID [--question TEXT], '
                  'с необязательными --checkpoint-db/--stream; бюджеты задаются только при --discuss. '
                  'Режимы исследования смешивать нельзя.', file=sys.stderr)
            return 2
        try:
            result = run_chat(args)
        except (ChatError, PersistenceError, ConfigurationError) as error:
            print(f'Ошибка: {error}', file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.resume is not None:
        if not args.resume.strip() or args.topic is not None or args.review or args.search or args.report or args.pause_after_plan or args.output_dir is not None:
            print('Ошибка: --resume допускает только THREAD_ID и --checkpoint-db; тему, режим и output-путь менять нельзя.', file=sys.stderr)
            return 2
    elif args.topic is None:
        parser.error('укажите --topic или --resume')
    if args.report and not (args.review and args.search):
        print('Ошибка: --report требует --review и --search.', file=sys.stderr)
        return 2
    if not args.report and not args.resume and (args.pause_after_plan or args.output_dir is not None or args.checkpoint_db is not None):
        print('Ошибка: параметры Persistence и Pause требуют полного режима --review --search --report.', file=sys.stderr)
        return 2
    if args.search and not args.review:
        print("Ошибка: --search требует --review и утверждение плана.", file=sys.stderr)
        return 2
    if args.review and not args.pause_after_plan and (sys.stdin is None or not sys.stdin.isatty()):
        print("Ошибка: --review требует интерактивный терминал для ввода решения.", file=sys.stderr)
        return 2
    try:
        if args.report or args.resume:
            result = persistent_run(args)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.review:
            graph = build_graph(review=True, search=args.search, checkpointer=InMemorySaver())
            config = {"configurable": {"thread_id": uuid4().hex}, 'max_concurrency': MAX_CONCURRENCY}
        else:
            graph = build_graph()
            config = None
        result = graph.invoke({"topic": args.topic}, config)
        if args.review:
            payload = result["__interrupt__"][0].value
            decision = request_review(payload["plan"])
            result = graph.invoke(Command(resume=decision), config)
    except (EmptyTopicError, ConfigurationError, PlanGenerationError, SearchError, ReportError, PersistenceError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
