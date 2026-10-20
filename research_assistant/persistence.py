"""File-backed checkpoint lifetime and compatibility checks for report threads."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

WORKFLOW_VERSION = 1
WORKFLOW_MODE = 'review_search_report'


class PersistenceError(Exception):
    """Expected database, thread lookup or workflow compatibility error."""


def workflow_settings(db: str, output_dir: str, thread_id: str) -> dict:
    return {'version': WORKFLOW_VERSION, 'mode': WORKFLOW_MODE,
            'checkpoint_db': str(Path(db).resolve()), 'output_dir': str(Path(output_dir).resolve()),
            'thread_id': thread_id}


@contextmanager
def open_saver(db: str, *, existing: bool = False):
    path = Path(db).resolve()
    if existing and not path.is_file():
        raise PersistenceError('База Checkpoints не найдена. Укажите прежний --checkpoint-db.')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PersistenceError('Не удалось создать каталог Checkpoints.') from error
    try:
        with SqliteSaver.from_conn_string(str(path)) as saver:
            yield saver
    except sqlite3.Error as error:
        raise PersistenceError('Ошибка SQLite Checkpoints. Проверьте путь, доступ и файл базы.') from error


def inspect_thread(graph, config: dict, db: str):
    snapshot = graph.get_state(config)
    if not snapshot.values:
        raise PersistenceError('Thread не найден в указанной базе Checkpoints.')
    settings = snapshot.values.get('workflow')
    if not isinstance(settings, dict) or settings.get('version') != WORKFLOW_VERSION or settings.get('mode') != WORKFLOW_MODE:
        raise PersistenceError('Несовместимая версия или режим сохранённого Workflow.')
    if (settings.get('thread_id') != config['configurable']['thread_id']
            or settings.get('checkpoint_db') != str(Path(db).resolve())
            or not isinstance(settings.get('output_dir'), str)
            or not Path(settings['output_dir']).is_absolute()):
        raise PersistenceError('Несовместимые сохранённые пути или thread_id Workflow.')
    return snapshot
