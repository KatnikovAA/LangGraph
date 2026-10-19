"""Terminal interface for preparing a research request."""

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from research_assistant.graph import EmptyTopicError, build_graph
from research_assistant.planning import ConfigurationError, PlanGenerationError
from research_assistant.schemas import ResearchPlan
from research_assistant.search import SearchError


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


def main(argv: list[str] | None = None) -> int:
    # Keep Cyrillic readable when Windows redirects stdout/stderr to pipes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Составление плана исследования")
    parser.add_argument("--topic", required=True, help="Тема исследования")
    parser.add_argument("--review", action="store_true", help="Проверить и утвердить план интерактивно")
    parser.add_argument("--search", action="store_true", help="Найти источники после утверждения плана")
    args = parser.parse_args(argv)
    if args.search and not args.review:
        print("Ошибка: --search требует --review и утверждение плана.", file=sys.stderr)
        return 2
    if args.review and (sys.stdin is None or not sys.stdin.isatty()):
        print("Ошибка: --review требует интерактивный терминал для ввода решения.", file=sys.stderr)
        return 2
    if args.review:
        checkpointer = InMemorySaver()
        graph = build_graph(review=True, search=args.search, checkpointer=checkpointer)
        config = {"configurable": {"thread_id": uuid4().hex}}
    else:
        graph = build_graph()
        config = None
    try:
        result = graph.invoke({"topic": args.topic}, config)
        if args.review:
            payload = result["__interrupt__"][0].value
            decision = request_review(payload["plan"])
            result = graph.invoke(Command(resume=decision), config)
    except (EmptyTopicError, ConfigurationError, PlanGenerationError, SearchError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
