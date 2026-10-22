"""Bounded memory writes authorized by the CURRENT explicit Human request."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import ToolRuntime
from research_assistant.user_memory import (MemoryError, ProfilePatch, NoteInput,
    apply_tool_operation, retrieve_memory, validate_user_id, store_identity)


@dataclass(frozen=True)
class MemoryContext:
    user_id: str
    thread_id: str
    store_path: str
    response_style: str | None = None

    def __post_init__(self):
        validate_user_id(self.user_id)
        # Match initialize_chat's canonical path, including Windows short-path aliases.
        object.__setattr__(self, 'store_path', str(Path(self.store_path).resolve()))
        if self.response_style not in (None, 'brief', 'detailed'):
            raise MemoryError('Неизвестный стиль Assistant.')


def memory_access(runtime, binding: dict | None) -> bool:
    context = runtime.context
    if not binding:
        if context is not None:
            raise MemoryError('Старый Chat без памяти нельзя привязать к пользователю. Создайте новый --discuss с --user-id.')
        return False
    if (not isinstance(context, MemoryContext) or runtime.store is None
            or binding.get('user_id') != context.user_id or binding.get('store_path') != context.store_path
            or binding.get('thread_id') != context.thread_id or binding.get('store_id') != store_identity(runtime.store)):
        raise MemoryError('Runtime Context не соответствует владельцу Chat или файлу Store.')
    return True


def memory_view(runtime, binding: dict | None, question: str) -> dict:
    if not memory_access(runtime, binding):
        return {}
    context = runtime.context
    return retrieve_memory(runtime.store, context.user_id, question)


def current_question(state: dict):
    history = state.get('context_history') or state.get('messages', [])
    return next(message for message in reversed(history) if isinstance(message, HumanMessage))


def requested_operation(question: str) -> str | None:
    patterns = {'update_profile': r'^(?:измени предпочтени[ея]|обнови профиль|запомни предпочтение|update profile|change preference)\b',
                'delete_note': r'^(?:забудь заметку|удали заметку|forget note|delete note)\b',
                'save_note': r'^(?:запомни|сохрани заметку|remember|save note)\b'}
    return next((operation for operation, pattern in patterns.items()
                 if re.search(pattern, question.strip(), re.IGNORECASE)), None)


def operation_results(messages: list) -> list[dict]:
    from langchain_core.messages import ToolMessage
    results = []
    for message in messages:
        if not isinstance(message, ToolMessage) or message.name not in MEMORY_TOOL_NAMES:
            continue
        try:
            value = json.loads(message.content)
        except (ValueError, TypeError):
            value = {}
        results.append({'tool': message.name, 'status': value.get('status', 'failed'),
                        'id': value.get('id'), 'present': value.get('present', False)})
    return results


def _write(operation: str, data: dict, runtime) -> str:
    try:
        context = runtime.context
        if not isinstance(context, MemoryContext) or runtime.store is None:
            raise MemoryError('Для памяти нужен диалог с --user-id.')
        binding = runtime.state.get('memory_binding')
        memory_access(runtime, binding)  # Verify owner/path before touching mutation namespaces.
        question = current_question(runtime.state)
        if requested_operation(question.content) != operation:
            raise MemoryError('Запись запрещена: нужен явный запрос текущего пользователя, а не Report или Summary.')
        call = next(call for call in runtime.state['messages'][-1].tool_calls if call['id'] == runtime.tool_call_id)
        expected = {'update_profile': {'preferences'}, 'save_note': {'note'}, 'delete_note': {'note_id'}}[operation]
        if set(call['args']) - expected:
            raise MemoryError('Лишние аргументы memory Tool запрещены; user_id/Namespace задаёт приложение.')
        origin = {'chat_thread_id': context.thread_id, 'tool_call_id': runtime.tool_call_id,
                  'turn_id': question.id}
        result = apply_tool_operation(runtime.store, context.user_id, operation, data, origin)
        return json.dumps(result, ensure_ascii=False)
    except MemoryError:
        return json.dumps({'error': 'memory_write_failed_or_denied', 'saved': False}, ensure_ascii=False)


@tool
def update_profile(preferences: ProfilePatch, runtime: ToolRuntime[MemoryContext]) -> str:
    """Update only requested response language/style/code language. Requires explicit change-preference request."""
    return _write('update_profile', preferences.model_dump(exclude_unset=True), runtime)


@tool
def save_note(note: NoteInput, runtime: ToolRuntime[MemoryContext]) -> str:
    """Save a bounded user note ONLY when current user explicitly asks remember/save note."""
    return _write('save_note', note.model_dump(), runtime)


@tool
def delete_note(note_id: str, runtime: ToolRuntime[MemoryContext]) -> str:
    """Delete one user note by exact ID ONLY on explicit forget/delete-note request."""
    return _write('delete_note', {'note_id': note_id}, runtime)


MEMORY_TOOLS = [update_profile, save_note, delete_note]
MEMORY_TOOL_NAMES = {tool.name for tool in MEMORY_TOOLS}
