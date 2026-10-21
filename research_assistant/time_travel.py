"""Prepare identifiable native branches; execution is always a separate operation."""

from uuid import uuid4
from langgraph.types import Overwrite
from pydantic import ValidationError
from research_assistant.history import research_checkpoint
from research_assistant.persistence import inspect_thread, PersistenceError
from research_assistant.schemas import ResearchPlan


def prepare_branch(graph, thread_id: str, checkpoint_id: str, db: str, *, operation: str, new_plan=None) -> dict:
    snapshot = research_checkpoint(graph, thread_id, checkpoint_id, db)
    inspect_thread(graph, snapshot.config, db)
    # Snapshot values are the input to review_plan. Pending interrupt metadata can
    # already be attached to this SAME checkpoint; it is not an approved State.
    values = snapshot.values
    if (snapshot.next != ('review_plan',) or not snapshot.tasks
            or any(t.name != 'review_plan' or t.error for t in snapshot.tasks)
            or values.get('status') != 'planned' or not values.get('normalized_topic')
            or any(values.get(k) for k in ('search_jobs', 'search_batches', 'sources', 'report_markdown', 'report_path'))):
        raise PersistenceError('Нужен Checkpoint после generate_plan перед завершением review_plan, без поиска и Report.')
    if operation not in ('fork', 'replay') or (operation == 'replay' and new_plan is not None):
        raise PersistenceError('Неизвестная операция ветвления или лишний Plan для Replay.')
    try:
        plan = ResearchPlan.model_validate(new_plan if operation == 'fork' else values.get('plan')).model_dump(mode='json')
    except ValidationError as error:
        raise PersistenceError('Альтернативный Plan должен соответствовать ResearchPlan: title и sections.') from error
    workflow = {**values['workflow'], 'artifact_id': uuid4().hex,
                'branch': {'operation': operation, 'checkpoint_id': checkpoint_id}}
    # Overwrite bypasses operator.add. [] alone would NOT clear a reducer channel.
    update = {'workflow': workflow, 'plan': plan, 'status': 'planned', 'search_jobs': [],
              'search_batches': Overwrite([]), 'sources': [], 'report_markdown': '', 'report_path': ''}
    # generate_plan's outgoing edge is review_plan. update_state creates a checkpoint,
    # does not execute generate_plan/review/API and must return the continuation config.
    return graph.update_state(snapshot.config, update, as_node='generate_plan')
