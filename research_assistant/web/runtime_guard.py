"""Fail closed before the dev runtime can discard incompatible persistence files."""
from importlib.metadata import version
import json
from pathlib import Path
import pickle


def guard_runtime(runtime: Path, *, versions=None):
    versions = versions if versions is not None else {name: version(name) for name in (
        'langgraph-api', 'langgraph-runtime-inmem', 'langgraph', 'langgraph-checkpoint')}
    marker = runtime / 'format.json'
    try:
        if marker.exists() and json.loads(marker.read_text(encoding='utf-8')) != versions:
            raise ValueError('Версии runtime изменились. Сохраните данные и восстановите прежнее окружение; автоматическая очистка запрещена.')
        data = runtime / '.langgraph_api'
        if data.exists():
            if any(data.glob('*.tmp')):
                raise ValueError('Обнаружена незавершённая запись runtime. Сохраните каталог для восстановления.')
            for file in data.glob('*.pckl'):
                # Native runtime uses pickle dicts. Only load this application's
                # trusted local files, never uploaded files or arbitrary client paths.
                with file.open('rb') as source:
                    loaded = pickle.load(source)
                if not isinstance(loaded, dict):
                    raise ValueError('Несовместимый формат runtime.')
                if file.name == '.langgraph_ops.pckl' and any(
                        not isinstance(loaded.get(k), list) for k in ('runs', 'threads', 'assistants', 'assistant_versions')):
                    raise ValueError('Несовместимые данные native runtime.')
    except ValueError:
        raise
    except Exception as error:
        # Startup boundary: native loader catches broad deserialization failures
        # and may remove files. Do not let it run after ANY preflight load error.
        raise ValueError('Не удалось проверить серверные данные. Файлы сохранены; восстановите совместимую резервную копию.') from None
    if not marker.exists():
        temp = marker.with_suffix('.tmp')
        temp.write_text(json.dumps(versions, sort_keys=True), encoding='utf-8')
        temp.replace(marker)
