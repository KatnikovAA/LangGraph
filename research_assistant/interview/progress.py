"""Real node lifecycle events, without provider data or hidden reasoning."""
from datetime import datetime, timezone
from uuid import uuid4, UUID
from langgraph.config import get_stream_writer

LABELS = {'prepare_interview': 'Проверяем тему и роль', 'ask_question': 'Аналитик формулирует вопрос',
          'search_sources': 'Ищем источники', 'answer_question': 'Эксперт готовит ответ',
          'summarize_interview': 'Собираем итог', 'save_report': 'Сохраняем отчёт'}


def project_progress(data: dict, run_id: str) -> dict | None:
    if not isinstance(data, dict) or data.get('node') not in LABELS:
        return None
    if data.get('status') not in ('running', 'done', 'error') or type(data.get('round')) is not int or data['round'] not in (0, 1, 2):
        return None
    try:
        UUID(data['execution_id'])
        stamp = datetime.fromisoformat(data['timestamp'])
        if stamp.tzinfo is None:
            return None
    except (ValueError, TypeError, KeyError):
        return None
    return {k: data[k] for k in ('node', 'round', 'execution_id', 'status', 'timestamp')} | {
        'run_id': run_id, 'label': LABELS[data['node']]}


def tracked(node, function):
    def invoke(state, config):
        round_number = state.get('round', 0)
        if node == 'ask_question':
            round_number = len(state.get('answers', [])) + 1
        base = {'node': node, 'round': round_number, 'execution_id': str(uuid4()), 'label': LABELS[node]}
        writer = get_stream_writer()
        def emit(status):
            event = {**base, 'status': status, 'timestamp': datetime.now(timezone.utc).isoformat()}
            writer(event)
            return event
        started = emit('running')
        try:
            update = function(state, config)
        except Exception:
            emit('error')
            raise
        finished = emit('done')
        return {**update, 'progress': [*state.get('progress', []), {**finished, 'started_at': started['timestamp']}]}
    return invoke
