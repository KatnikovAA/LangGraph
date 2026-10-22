"""Connect a separate chat thread to immutable completed research checkpoints."""

import sys
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from research_assistant.chat import (
    CHAT_MODE, CHAT_VERSION, MEMORY_CHAT_VERSION, ChatError, build_chat_graph, initialize_chat,
    validate_materials,
    validate_context_state,
)
from research_assistant.chat_context import ContextBudget
from research_assistant.graph import build_graph
from research_assistant.persistence import inspect_thread, open_saver
from research_assistant.history import research_checkpoint
from research_assistant.user_memory import (MemoryError, open_memory_store, validate_user_id, DEFAULT_MEMORY_DB,
                                            store_identity)
from research_assistant.memory_tools import MemoryContext


def research_materials(saver, research_id: str, db: str, checkpoint_id: str | None = None, *, include_checkpoint=False) -> dict:
    """Read a research checkpoint without invoking its workflow or reading files."""
    graph = build_graph(review=True, search=True, report=True, checkpointer=saver)
    config = {'configurable': {'thread_id': research_id}}
    snapshot = (research_checkpoint(graph, research_id, checkpoint_id, db) if checkpoint_id
                else inspect_thread(graph, config, db))
    inspect_thread(graph, snapshot.config, db)
    if snapshot.next or snapshot.values.get('status') != 'completed':
        raise ChatError('Обсуждение доступно только для завершённого Research Thread со статусом completed.')
    data = validate_materials({'research_thread_id': research_id,
                              'report_markdown': snapshot.values.get('report_markdown'),
                              'sources': snapshot.values.get('sources')})
    return {**data, 'research_checkpoint_id': snapshot.config['configurable']['checkpoint_id']} if include_checkpoint else data


def inspect_chat(graph, config: dict, db: str, saver):
    snapshot = graph.get_state(config)
    if snapshot.created_at is None:
        raise ChatError('Chat Thread не найден в указанной базе.')
    settings = snapshot.values.get('chat_settings')
    if (not isinstance(settings, dict) or settings.get('version') not in (CHAT_VERSION, MEMORY_CHAT_VERSION)
            or settings.get('mode') != CHAT_MODE):
        research_id = settings.get('research_thread_id') if isinstance(settings, dict) else None
        hint = f' --discuss {research_id} --question "Ваш вопрос"' if isinstance(research_id, str) else ' --discuss RESEARCH_ID --question "Ваш вопрос"'
        raise ChatError('Несовместимая версия или режим Chat Thread. Нужна Chat version=3 с Research checkpoint_id; '
                        'старые данные сохранены. Создайте новый Chat Thread по тому же исследованию:' + hint)
    research_id = settings.get('research_thread_id')
    research_cp = settings.get('research_checkpoint_id')
    if (settings.get('thread_id') != config['configurable']['thread_id']
            or settings.get('checkpoint_db') != db or not isinstance(research_id, str) or not research_id
            or snapshot.values.get('research_thread_id') != research_id
            or research_id == config['configurable']['thread_id']
            or not isinstance(research_cp, str) or not research_cp):
        raise ChatError('Некорректная привязка Chat Thread к исследованию или базе.')
    saved = validate_materials({key: snapshot.values.get(key) for key in ('research_thread_id', 'report_markdown', 'sources')})
    if saved != research_materials(saver, research_id, db, research_cp):
        raise ChatError('Материалы Chat Thread не совпадают со связанным исследованием.')
    validate_context_state(snapshot.values)
    if settings['version'] == MEMORY_CHAT_VERSION:
        binding = snapshot.values.get('memory_binding')
        keys = ('user_id', 'store_path', 'store_id', 'thread_id')
        if (not isinstance(binding, dict) or any(not isinstance(binding.get(k), str) or not binding[k] for k in keys)
                or any(settings.get(k) != binding[k] for k in keys)
                or not Path(binding['store_path']).is_absolute()):
            raise MemoryError('Некорректная сохранённая привязка Chat к пользователю/Store.')
        validate_user_id(binding['user_id'])
    return snapshot


def run_chat(args) -> dict:
    question = args.question
    if question is not None and not question.strip():
        raise ChatError('Вопрос не должен быть пустым.')
    db = str(Path(args.checkpoint_db or '.research_assistant/checkpoints.sqlite').resolve())
    chat_id = args.chat if args.chat is not None else uuid4().hex
    if not chat_id.strip():
        raise ChatError('Укажите непустой Chat Thread ID.')
    config = {'configurable': {'thread_id': chat_id}, 'max_concurrency': 2, 'recursion_limit': 30}
    with ExitStack() as resources:
        saver = resources.enter_context(open_saver(db, existing=True))
        user_id = getattr(args, 'user_id', None)
        requested_path = getattr(args, 'memory_db', None)
        context, store, store_path = None, None, None
        probe = build_chat_graph(checkpointer=saver)
        if args.chat is not None:
            snapshot = inspect_chat(probe, config, db, saver)
            binding = snapshot.values.get('memory_binding', {})
            if snapshot.values['chat_settings']['version'] == MEMORY_CHAT_VERSION:
                if user_id != binding['user_id']:
                    raise MemoryError('Для продолжения укажите прежний --user-id; смена владельца Chat запрещена.')
                store_path = str(Path(requested_path or binding['store_path']).resolve())
                if store_path != binding['store_path'] or store_path == db:
                    raise MemoryError('Путь --memory-db отличается от сохранённого Store этого Chat.')
                store = resources.enter_context(open_memory_store(store_path, existing=True))
                if store_identity(store) != binding['store_id']:
                    raise MemoryError('Файл Store заменён другим хранилищем; Resume запрещён.')
            elif user_id is not None or requested_path is not None:
                raise MemoryError('Chat версии 3 остаётся без памяти/владельца. Создайте новый --discuss с --user-id.')
        elif user_id is not None:
            validate_user_id(user_id)
            store_path = str(Path(requested_path or DEFAULT_MEMORY_DB).resolve())
            if store_path == db:
                raise MemoryError('Store и Checkpointer должны использовать разные файлы.')
            store = resources.enter_context(open_memory_store(store_path))
        elif requested_path is not None:
            raise MemoryError('--memory-db для нового Chat требует явный --user-id.')
        if store is not None:
            context = MemoryContext(user_id, chat_id, store_path)
        budget_options = {field: getattr(args, flag, None) for field, flag in (
            ('input_tokens', 'context_budget'), ('answer_reserve', 'answer_reserve'),
            ('summary_threshold', 'summary_threshold'), ('summary_tokens', 'summary_budget'),
            ('recent_turns', 'recent_turns'))}
        graph = build_chat_graph(checkpointer=saver, store=store, context_budget=ContextBudget(
            **{key: value for key, value in budget_options.items() if value is not None}))
        if args.discuss is not None:
            materials = research_materials(saver, args.discuss, db, getattr(args, 'research_checkpoint_id', None),
                                           include_checkpoint=True)
            initialize_chat(graph, config, materials, db, user_id=user_id, store_path=store_path)
            snapshot = graph.get_state(config)
        else:
            snapshot = inspect_chat(graph, config, db, saver)
        print(f'Chat Thread: {chat_id}\nResearch Thread: {snapshot.values["research_thread_id"]}\nCheckpoints: {db}',
              file=sys.stderr, flush=True)
        if snapshot.next:
            if question is not None:
                raise ChatError('Предыдущий вопрос не завершён. Продолжите через --chat ID без --question; новый вопрос пока не принят.')
            graph_input = None
        else:
            if question is None:
                raise ChatError('Нет незавершённого вопроса. Укажите --question для новой реплики.')
            graph_input = {'question': question}
        if getattr(args, 'stream', False):
            from research_assistant.chat_streaming import stream_chat
            result = stream_chat(graph, graph_input, config, context=context)
        else:
            result = graph.invoke(graph_input, config, durability='sync', context=context)
        diagnostics = graph.get_state(config).values.get('memory_diagnostics', {})
        return {**result, **({'memory_selection': diagnostics} if context else {}),
                'chat_thread_id': chat_id, 'research_thread_id': snapshot.values['research_thread_id'],
                'research_checkpoint_id': snapshot.values['chat_settings']['research_checkpoint_id'],
                'checkpoint_db': db}
