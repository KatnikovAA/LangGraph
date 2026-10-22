"""User Profile/Collection on a real, separately-lived LangGraph SqliteStore."""

import hashlib
import asyncio
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal
from uuid import uuid4

from langgraph.store.base import PutOp, SearchOp
from langgraph.store.sqlite import SqliteStore
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

DEFAULT_MEMORY_DB = '.research_assistant/memory.sqlite'
MAX_SELECTED_NOTES = 3
MAX_MEMORY_CHARS = 2400
_mutation_lock = RLock()


class MemoryError(Exception):
    """Expected user memory validation/storage failure, without provider/SQL details."""


class LocalMemoryStore(SqliteStore):
    """Native backend; explicitly limit optional features to the supported CLI contract."""
    @property
    def supports_ttl(self):
        return False

    @contextmanager
    def _cursor(self, *, transaction=True):
        # Installed native 3.1.2 commits in finally even after an exception.
        # Roll back failed batches so a note and its idempotency receipt stay atomic.
        if not self.is_setup:
            self.setup()
        with self.lock:
            if transaction:
                self.conn.execute('BEGIN IMMEDIATE')
            cursor = self.conn.cursor()
            try:
                yield cursor
                if transaction:
                    self.conn.commit()
            except BaseException:
                if transaction:
                    self.conn.rollback()
                raise
            finally:
                cursor.close()

    def _prepare_batch_search_queries(self, ops):
        queries, requests = super()._prepare_batch_search_queries(ops)
        queries = [(sql.replace(' ORDER BY updated_at DESC', ' ORDER BY updated_at DESC, prefix ASC, key ASC'),
                    params, refresh) for sql, params, refresh in queries]
        return queries, requests

    async def abatch(self, ops):
        return await asyncio.to_thread(self.batch, list(ops))

    def batch(self, ops):
        ops = list(ops)
        for op in ops:
            if isinstance(op, SearchOp):
                if op.query is not None:
                    raise NotImplementedError('Semantic Search не поддерживается.')
                if op.filter and any(isinstance(value, (dict, list)) for value in op.filter.values()):
                    raise NotImplementedError('Поддерживаются только простые фильтры равенства верхнего уровня.')
                if op.limit < 0 or op.offset < 0:
                    raise MemoryError('limit и offset должны быть неотрицательными.')
            if isinstance(op, PutOp) and (op.ttl is not None or op.index not in (None, False)):
                raise NotImplementedError('TTL и vector indexing не поддерживаются.')
        try:
            return super().batch(ops)
        except sqlite3.Error as error:
            raise MemoryError('Ошибка SQLite Store; операция с памятью не подтверждена.') from error


@contextmanager
def open_memory_store(path: str, *, existing: bool = False):
    target = Path(path).resolve()
    if existing and not target.is_file():
        raise MemoryError('Файл Store не найден. Восстановите прежнюю память; новая база при Resume не создаётся.')
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with LocalMemoryStore.from_conn_string(str(target)) as store:
            if store.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoints'").fetchone():
                raise MemoryError('Это файл Checkpointer. Для Store укажите отдельный --memory-db.')
            store.setup()
            if store.get(('_research_assistant', 'metadata'), 'identity') is None:
                if existing:
                    raise MemoryError('В Store отсутствует идентификатор приложения. Подмена памяти при Resume запрещена.')
                store.put(('_research_assistant', 'metadata'), 'identity', {'id': uuid4().hex})
            yield store
    except (sqlite3.Error, OSError) as error:
        raise MemoryError('Не удалось открыть локальный Store памяти. Проверьте путь и доступ.') from error


def store_identity(store) -> str:
    item = store.get(('_research_assistant', 'metadata'), 'identity')
    if item is None or not isinstance(item.value.get('id'), str):
        raise MemoryError('В Store отсутствует идентификатор приложения.')
    return item.value['id']


def validate_user_id(user_id: str) -> str:
    if (not isinstance(user_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', user_id)
            or user_id == 'langgraph'):
        raise MemoryError('user_id: от 1 до 64 латинских букв, цифр, _ или -. Это разделение данных, не аутентификация.')
    return user_id


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: ShortText = 'русский'
    style: Literal['brief', 'balanced', 'detailed'] = 'brief'
    code_language: ShortText | None = None


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: ShortText | None = None
    style: Literal['brief', 'balanced', 'detailed'] | None = None
    code_language: ShortText | None = None


class NoteInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
    topic: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None
    tags: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=24)]] = Field(default_factory=list, max_length=5)


class Note(NoteInput):
    origin: dict[str, str]


def _validate(schema, data):
    try:
        return schema.model_validate(data).model_dump(mode='json')
    except ValidationError as error:
        raise MemoryError('Поля памяти не прошли проверку схемы или ограничения размера.') from error


def get_profile(store, user_id: str) -> dict:
    item = store.get((validate_user_id(user_id), 'profile'), 'preferences')
    return _validate(Profile, item.value if item else {})


def update_profile(store, user_id: str, patch: dict) -> dict:
    # Process-local serialization preserves partial updates across parallel Tools.
    with _mutation_lock:
        _validate(ProfilePatch, patch)
        if not patch:
            raise MemoryError('Укажите хотя бы одно поле Profile.')
        value = _validate(Profile, {**get_profile(store, user_id), **patch})
        store.put((user_id, 'profile'), 'preferences', value)
        return value


def reset_profile(store, user_id: str) -> None:
    store.delete((validate_user_id(user_id), 'profile'), 'preferences')


def save_note(store, user_id: str, data: dict, *, note_id=None, origin=None) -> str:
    value = _validate(Note, {**_validate(NoteInput, data), 'origin': origin or {'kind': 'cli'}})
    identifier = note_id or uuid4().hex
    store.put((validate_user_id(user_id), 'notes'), identifier, value)
    return identifier


def list_notes(store, user_id: str) -> list[dict]:
    namespace = (validate_user_id(user_id), 'notes')
    items, offset = [], 0
    while True:
        page = store.search(namespace, limit=100, offset=offset)
        if not page:
            break
        items.extend(item for item in page if item.namespace == namespace)
        offset += len(page)
    return [{'id': item.key, **_validate(Note, item.value), 'created_at': item.created_at.isoformat(),
             'updated_at': item.updated_at.isoformat()} for item in sorted(items, key=lambda item: item.key)]


def get_note(store, user_id: str, note_id: str):
    item = store.get((validate_user_id(user_id), 'notes'), note_id)
    if item is None:
        raise MemoryError('Заметка с указанным ID не найдена у этого пользователя.')
    return {'id': item.key, **_validate(Note, item.value)}


def update_note(store, user_id: str, note_id: str, data: dict) -> dict:
    with _mutation_lock:
        old = get_note(store, user_id, note_id)
        if not data or set(data) - {'text', 'topic', 'tags'}:
            raise MemoryError('Для изменения заметки нужны text/topic/tags.')
        value = _validate(Note, {**{k: v for k, v in old.items() if k != 'id'}, **data})
        store.put((user_id, 'notes'), note_id, value)
        return {'id': note_id, **value}


def delete_note(store, user_id: str, note_id: str) -> None:
    get_note(store, user_id, note_id)
    store.delete((user_id, 'notes'), note_id)


def words(text: str) -> set[str]:
    return {word for word in re.findall(r'[\w]+', text.casefold()) if len(word) >= 3}


def retrieve_memory(store, user_id: str, question: str) -> dict:
    profile = get_profile(store, user_id)
    terms = words(question)
    ranked = []
    for note in list_notes(store, user_id):
        matched = terms & words(' '.join([note['text'], note.get('topic') or '', *note['tags']]))
        if matched:
            ranked.append((-len(matched), note['id'], note, sorted(matched)))
    selected = []
    for _, identifier, note, matched in sorted(ranked):
        candidate = {'id': identifier, 'text': note['text'], 'topic': note['topic'], 'tags': note['tags'],
                     'reason': 'Совпали слова: ' + ', '.join(matched)}
        trial = {'profile': profile, 'notes': selected + [candidate]}
        if len(json.dumps(trial, ensure_ascii=False)) <= MAX_MEMORY_CHARS:
            selected.append(candidate)
        if len(selected) >= MAX_SELECTED_NOTES:
            break
    return {'profile': profile, 'notes': selected}


def apply_tool_operation(store, user_id: str, operation: str, data: dict, origin: dict) -> dict:
    """Data + receipt in one native batch. Same saved call never creates a second note."""
    user_id = validate_user_id(user_id)
    identifier = hashlib.sha256(json.dumps({**origin, 'operation': operation}, sort_keys=True).encode()).hexdigest()
    receipt_ns = (user_id, 'memory_operations')
    with _mutation_lock:
        receipt = store.get(receipt_ns, identifier)
        if receipt:
            result = receipt.value
            namespace, key = tuple(result['namespace']), result['key']
            return {'status': 'already_applied', 'operation': operation,
                    'id': key, 'present': store.get(namespace, key) is not None}
        if operation == 'update_profile':
            _validate(ProfilePatch, data)
            if not data:
                raise MemoryError('Пустое обновление Profile.')
            namespace, key = (user_id, 'profile'), 'preferences'
            value = _validate(Profile, {**get_profile(store, user_id), **data})
        elif operation == 'save_note':
            namespace, key = (user_id, 'notes'), identifier
            value = _validate(Note, {**_validate(NoteInput, data), 'origin': origin})
        elif operation == 'delete_note':
            key = data.get('note_id')
            if not isinstance(key, str) or not key:
                raise MemoryError('Нужен ID заметки.')
            get_note(store, user_id, key)
            namespace, value = (user_id, 'notes'), None
        else:
            raise MemoryError('Неизвестная операция памяти.')
        status = 'deleted' if operation == 'delete_note' else 'saved'
        result = {'status': status, 'namespace': list(namespace), 'key': key}
        store.batch([PutOp(namespace, key, value), PutOp(receipt_ns, identifier, result)])
        return {'status': status, 'id': key, 'present': value is not None}
