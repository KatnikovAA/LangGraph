"""Terminal interface for preparing a research request."""

import argparse
import json
import sys

from research_assistant.graph import EmptyTopicError, build_graph


def main(argv: list[str] | None = None) -> int:
    # Keep Cyrillic readable when Windows redirects stdout/stderr to pipes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Подготовка заявки на исследование")
    parser.add_argument("--topic", required=True, help="Тема исследования")
    args = parser.parse_args(argv)
    graph = build_graph()
    try:
        result = graph.invoke({"topic": args.topic})
    except EmptyTopicError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
