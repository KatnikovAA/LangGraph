"""Connect a separate chat thread to immutable completed research checkpoints."""

import sys
from pathlib import Path
from uuid import uuid4

from research_assistant.chat import (
    CHAT_MODE, CHAT_VERSION, ChatError, build_chat_graph, initialize_chat,
    validate_materials,
)
from research_assistant.graph import build_graph
from research_assistant.persistence import inspect_thread, open_saver


def research_materials(saver, research_id: str, db: str) -> dict:
    """Read a research checkpoint without invoking its workflow or reading files."""
    graph = build_graph(review=True, search=True, report=True, checkpointer=saver)
    config = {'configurable': {'thread_id': research_id}}
    snapshot = inspect_thread(graph, config, db)
    if snapshot.next or snapshot.values.get('status') != 'completed':
        raise ChatError('Обсуждение доступно только для завершённого Research Thread со статусом completed.')
    return validate_materials({'research_thread_id': research_id,
                              'report_markdown': snapshot.values.get('report_markdown'),
                              'sources': snapshot.values.get('sources')})


def inspect_chat(graph, config: dict, db: str, saver):
    snapshot = graph.get_state(config)
    if snapshot.created_at is None:
        raise ChatError('Chat Thread не найден в указанной базе.')
    settings = snapshot.values.get('chat_settings')
    if (not isinstance(settings, dict) or settings.get('version') != CHAT_VERSION
            or settings.get('mode') != CHAT_MODE):
        raise ChatError('Несовместимая версия или режим Chat Thread; Research Thread не является Chat Thread.')
    research_id = settings.get('research_thread_id')
    if (settings.get('thread_id') != config['configurable']['thread_id']
            or settings.get('checkpoint_db') != db or not isinstance(research_id, str) or not research_id
            or snapshot.values.get('research_thread_id') != research_id
            or research_id == config['configurable']['thread_id']):
        raise ChatError('Некорректная привязка Chat Thread к исследованию или базе.')
    saved = validate_materials({key: snapshot.values.get(key) for key in ('research_thread_id', 'report_markdown', 'sources')})
    if saved != research_materials(saver, research_id, db):
        raise ChatError('Материалы Chat Thread не совпадают со связанным исследованием.')
    return snapshot


def run_chat(args) -> dict:
    question = args.question
    if question is not None and not question.strip():
        raise ChatError('Вопрос не должен быть пустым.')
    db = str(Path(args.checkpoint_db or '.research_assistant/checkpoints.sqlite').resolve())
    chat_id = args.chat if args.chat is not None else uuid4().hex
    if not chat_id.strip():
        raise ChatError('Укажите непустой Chat Thread ID.')
    config = {'configurable': {'thread_id': chat_id}, 'max_concurrency': 2, 'recursion_limit': 20}
    with open_saver(db, existing=True) as saver:
        graph = build_chat_graph(checkpointer=saver)
        if args.discuss is not None:
            materials = research_materials(saver, args.discuss, db)
            initialize_chat(graph, config, materials, db)
            snapshot = graph.get_state(config)
        else:
            snapshot = inspect_chat(graph, config, db, saver)
        print(f'Chat Thread: {chat_id}\nResearch Thread: {snapshot.values["research_thread_id"]}\nCheckpoints: {db}',
              file=sys.stderr, flush=True)
        if snapshot.next:
            if question is not None:
                raise ChatError('Предыдущий вопрос не завершён. Продолжите через --chat ID без --question; новый вопрос пока не принят.')
            result = graph.invoke(None, config, durability='sync')
        else:
            if question is None:
                raise ChatError('Нет незавершённого вопроса. Укажите --question для новой реплики.')
            result = graph.invoke({'question': question}, config, durability='sync')
        return {**result, 'chat_thread_id': chat_id, 'research_thread_id': snapshot.values['research_thread_id'],
                'checkpoint_db': db}
