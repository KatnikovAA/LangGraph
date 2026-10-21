"""Read-only Research checkpoint inspection and safe snapshot summaries."""

from research_assistant.persistence import PersistenceError, inspect_thread


def research_history(graph, thread_id: str, db: str) -> list:
    config = {'configurable': {'thread_id': thread_id}}
    stored = graph.checkpointer.get_tuple(config)
    if stored and stored.checkpoint.get('channel_values', {}).get('chat_settings'):
        raise PersistenceError('Это Chat Thread; History/Time Travel поддерживают только Research.')
    latest = graph.get_state(config)
    if latest.values.get('chat_settings'):
        raise PersistenceError('Это Chat Thread; History/Time Travel поддерживают только Research.')
    inspect_thread(graph, config, db)
    return list(graph.get_state_history(config))


def research_checkpoint(graph, thread_id: str, checkpoint_id: str, db: str):
    if not isinstance(checkpoint_id, str) or not checkpoint_id.strip():
        raise PersistenceError('Укажите непустой checkpoint_id.')
    # Explicit membership, including snapshots with no populated workflow yet.
    history = research_history(graph, thread_id, db)
    if not any(s.config['configurable']['checkpoint_id'] == checkpoint_id for s in history):
        raise PersistenceError('Checkpoint не найден в указанном Research Thread.')
    snapshot = graph.get_state({'configurable': {'thread_id': thread_id, 'checkpoint_ns': '',
                                                'checkpoint_id': checkpoint_id}})
    if snapshot.created_at is None or snapshot.config['configurable'].get('checkpoint_id') != checkpoint_id:
        raise PersistenceError('Checkpoint не найден; подстановка latest запрещена.')
    return snapshot


def stop_kind(snapshot) -> str:
    if any(task.error is not None for task in snapshot.tasks):
        return 'error'
    if any(task.interrupts for task in snapshot.tasks):
        return 'dynamic_interrupt'
    if not snapshot.next:
        return 'completed'
    if (snapshot.next == ('prepare_search',)
            and snapshot.values.get('workflow', {}).get('break_before_search', False)):
        return 'static_breakpoint'
    return 'pending'


def describe_snapshot(snapshot) -> dict:
    values = snapshot.values
    plan = values.get('plan') or {}
    config = snapshot.config['configurable']
    parent = (snapshot.parent_config or {}).get('configurable', {})
    return {'thread_id': config['thread_id'], 'checkpoint_id': config['checkpoint_id'],
            'parent_checkpoint_id': parent.get('checkpoint_id'), 'created_at': snapshot.created_at,
            'status': values.get('status'), 'next': list(snapshot.next), 'stop_kind': stop_kind(snapshot),
            'plan': {'title': plan.get('title'), 'sections': len(plan.get('sections', []))},
            'report': {'available': bool(values.get('report_markdown')), 'path': values.get('report_path')},
            'artifact_id': values.get('workflow', {}).get('artifact_id'),
            'branch': values.get('workflow', {}).get('branch')}
