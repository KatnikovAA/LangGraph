"""Find a resumable parent snapshot by stable Turn identity, never question text."""


def pending_checkpoint(history, current_values):
    def human_id(values):
        return next((m.get('id') for m in reversed(values.get('messages', [])) if m.get('type') == 'human'), None)
    identifier = human_id(current_values)
    if identifier is None:
        return None
    for point in history:
        values = point.get('values') or {}
        if (len(point.get('next', [])) == 1 and point['next'][0] in
                {'load_memory', 'context_gate', 'summarize', 'prepare_context', 'run_agent'}
                and values.get('status') == 'answering'
                and human_id(values) == identifier):
            return point['checkpoint']['checkpoint_id']
    return None
