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
            snapshot = inspect_thread(probe, config, db)
            output = snapshot.values['workflow']['output_dir']
            graph = build_graph(review=True, search=True, report=True, output_dir=output, checkpointer=saver)
            if not snapshot.next:
                result = dict(snapshot.values)
            elif any(task.interrupts for task in snapshot.tasks):
                require_terminal()
                decision = request_review(snapshot.values['plan'])
                result = graph.invoke(Command(resume=decision), config, durability='sync')
            else:
                result = graph.invoke(None, config, durability='sync')
                if result.get('__interrupt__'):
                    require_terminal()
                    decision = request_review(result['__interrupt__'][0].value['plan'])
                    result = graph.invoke(Command(resume=decision), config, durability='sync')
        else:
            output = str(Path(args.output_dir or 'reports').resolve())
            if not args.pause_after_plan:
                require_terminal()
            graph = build_graph(review=True, search=True, report=True, output_dir=output, checkpointer=saver)
            result = graph.invoke({'topic': args.topic, 'workflow': workflow_settings(db, output, thread_id)},
                                  config, durability='sync')
            if not args.pause_after_plan:
                decision = request_review(result['__interrupt__'][0].value['plan'])
                result = graph.invoke(Command(resume=decision), config, durability='sync')
        paused = bool(result.get('__interrupt__'))
        return {key: value for key, value in result.items() if key != '__interrupt__'} | {
            'thread_id': thread_id, 'checkpoint_db': db, 'paused': paused}


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
    args = parser.parse_args(argv)
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
