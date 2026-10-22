"""Application orchestration through Agent Server SDK, never CLI subprocesses."""
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
from uuid import UUID, uuid5, NAMESPACE_URL
from starlette.exceptions import HTTPException
from langgraph_sdk import get_client
from research_assistant.web.journal import RequestJournal
from research_assistant.chat import validate_materials
from research_assistant.chat_context import ContextBudget
from research_assistant.schemas import ResearchPlan, review_decision_adapter
from research_assistant.user_memory import (open_memory_store, store_identity, validate_user_id,
    get_profile, update_profile, reset_profile, list_notes, save_note, update_note, delete_note, retrieve_memory)


class WebService:
    def __init__(self, settings):
        self.settings = settings
        self.client = get_client(url=settings.agent_url, api_key=None)
        self.journal = RequestJournal(settings.data_root)
        self.lock = asyncio.Lock()

    async def owned(self, user, thread):
        validate_user_id(user)
        if not isinstance(thread, str):
            raise ValueError('Thread ID должен быть строкой UUID.')
        UUID(thread)
        data = await self.client.threads.get(thread)
        if data['metadata'].get('user_id') != user or data['metadata'].get('ra_web') != 1:
            raise HTTPException(403, 'Thread недоступен выбранному пользователю.')
        return data

    async def threads(self, user):
        validate_user_id(user)
        return await self.client.threads.search(metadata={'user_id': user, 'ra_web': 1}, limit=100)

    async def state(self, user, thread, checkpoint=None):
        await self.owned(user, thread)
        if checkpoint is not None:
            if not isinstance(checkpoint, str):
                raise ValueError('Checkpoint ID должен быть строкой UUID.')
            UUID(checkpoint)
        data = await self.client.threads.get_state(thread, checkpoint_id=checkpoint)
        if checkpoint is not None and (data.get('checkpoint') or {}).get('checkpoint_id') != checkpoint:
            raise HTTPException(404, 'Checkpoint не найден в Thread.')
        return data

    async def assistants(self):
        result = []
        for style in ('brief', 'detailed'):
            identifier = str(uuid5(NAMESPACE_URL, 'research-assistant:web:chat:' + style))
            item = await self.client.assistants.create('chat', assistant_id=identifier,
                name='Chat ' + style, config={'configurable': {'response_style': style}},
                metadata={'ra_web': 1}, if_exists='do_nothing')
            result.append({'id': item['assistant_id'], 'style': style,
                           'description': 'Краткий ответ, ориентир 80 слов' if style == 'brief' else 'Подробный ответ, ориентир 200 слов'})
        return result

    async def recover(self, user, request_id, operation, payload):
        validate_user_id(user)
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 128:
            raise ValueError('Нужен корректный request_id.')
        if not isinstance(payload, dict) or operation not in ('create_research', 'create_interview', 'review', 'create_chat', 'ask', 'resume'):
            raise ValueError('Некорректный сохранённый запрос.')
        async with self.lock:
            old = self.journal.lookup(user, request_id, {'operation': operation, **payload})
            if old is None:
                return {'recovery': 'not_received', 'message': 'Сервер не зарегистрировал запрос. Можно явно отправить сохранённый запрос с тем же ID.'}
            thread = old.get('thread_id') or payload.get('thread_id')
            if not thread:
                return {'recovery': 'unconfirmed', 'message': 'Run не подтверждён. Проверьте список исследований; автоматического повтора нет.'}
            info = await self.owned(user, thread)
            if not old.get('run_id'):
                candidates = await self.client.runs.list(thread, limit=100)
                found = next((r for r in candidates if r.get('metadata', {}).get('request_id') == request_id), None)
                if found:
                    old['run_id'] = found['run_id']
                    self.journal.bind_run(user, request_id, thread, found['run_id'])
            if old.get('run_id'):
                return {'recovery': 'found', 'thread_id': thread, 'run_id': old['run_id'], 'kind': info['metadata']['kind']}
            return {'recovery': 'unconfirmed', 'thread_id': thread,
                    'message': 'Thread сохранён, но создание Run не подтверждено. Проверьте его состояние; новый Run автоматически не запускается.'}

    async def run(self, user, request_id, operation, payload):
        validate_user_id(user)
        if operation == 'create_interview':
            from research_assistant.interview.schemas import validate_interview_input
            validate_interview_input(payload.get('topic'), payload.get('clarification', ''))
        if operation == 'create_research' and (not isinstance(payload.get('topic'), str) or not payload['topic'].strip()):
            raise ValueError('Тема не должна быть пустой.')
        if operation in ('ask', 'create_chat') and (not isinstance(payload.get('question'), str) or not payload['question'].strip()):
            raise ValueError('Вопрос не должен быть пустым.')
        if operation == 'create_chat':
            pinned = payload.get('research_checkpoint_id')
            if not isinstance(pinned, str) or not pinned:
                raise ValueError('Для Chat нужен явный Research Checkpoint ID; latest автоматически не выбирается.')
            UUID(pinned)
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 128:
            raise ValueError('Нужен request_id длиной 8–128 символов.')
        async with self.lock:
            # Validate scope BEFORE accepting the request or disclosing a previous result.
            thread = payload.get('thread_id')
            if thread:
                owned = await self.owned(user, thread)
                required_kind = {'review': 'research', 'ask': 'chat'}.get(operation)
                if required_kind and owned['metadata'].get('kind') != required_kind:
                    raise ValueError('Операция не соответствует типу Thread.')
            if operation == 'create_chat':
                await self.owned(user, payload['research_thread_id'])
            old = self.journal.reserve(user, request_id, {'operation': operation, **payload})
            if old and old.get('run_id'):
                return old
            if old:
                # Recover a lost create response, but never silently issue a second Run.
                if old.get('thread_id'):
                    candidates = await self.client.runs.list(old['thread_id'], limit=100)
                    found = next((r for r in candidates if r.get('metadata', {}).get('request_id') == request_id), None)
                    if found:
                        self.journal.bind_run(user, request_id, old['thread_id'], found['run_id'])
                        return {'thread_id': old['thread_id'], 'run_id': found['run_id']}
                raise HTTPException(409, 'Исход прежнего запроса не подтверждён. Обновите состояние; автоматический повтор отключён.')
            if operation in ('create_research', 'create_interview', 'create_chat'):
                kind = {'create_research': 'research', 'create_interview': 'interview', 'create_chat': 'chat'}[operation]
                thread = str(uuid5(NAMESPACE_URL, f'ra-web:{user}:{request_id}'))
                title = payload.get('topic', 'Обсуждение отчёта')
                if kind == 'chat':
                    material = await self.state(user, payload['research_thread_id'], payload['research_checkpoint_id'])
                    if material['values'].get('status') != 'completed':
                        raise ValueError('Для Chat нужен завершённый Research Checkpoint.')
                    title = material['values']['normalized_topic']
                metadata = {'user_id': user, 'kind': kind, 'ra_web': 1, 'title': title[:160]}
                await self.client.threads.create(thread_id=thread, metadata=metadata, graph_id=kind, if_exists='do_nothing')
                self.journal.bind_run(user, request_id, thread, None)
            state = await self.state(user, thread)
            values = state.get('values') or {}
            command, input_data, checkpoint = None, None, None
            info = await self.owned(user, thread)
            assistant = info['metadata']['kind']
            if assistant not in ('research', 'interview', 'chat'):
                raise ValueError('Неизвестный тип Workflow.')
            context = None
            if operation == 'create_interview':
                input_data = {'topic': payload['topic'], 'clarification': payload.get('clarification', ''),
                              'workflow': {'version': 'web-1', 'mode': 'interview'}}
            elif operation == 'create_research':
                if not isinstance(payload.get('topic'), str) or not payload['topic'].strip():
                    raise ValueError('Тема не должна быть пустой.')
                input_data = {'topic': payload['topic'], 'workflow': {'version': 'web-1', 'mode': 'review_search_report',
                    'output_dir': str(self.settings.reports), 'thread_id': thread}}
            elif operation == 'review':
                if state.get('next') != ['review_plan']:
                    raise HTTPException(409, 'Сейчас план не ожидает Review.')
                decision = review_decision_adapter.validate_python(payload['decision']).model_dump(mode='json')
                command = {'resume': decision}
            elif operation == 'create_chat':
                research = await self.state(user, payload['research_thread_id'], payload['research_checkpoint_id'])
                rv = research['values']
                if rv.get('status') != 'completed':
                    raise ValueError('Для Chat нужен завершённый Research Checkpoint.')
                source_info = await self.owned(user, payload['research_thread_id'])
                source_kind = source_info['metadata'].get('kind')
                if source_kind == 'interview':
                    from research_assistant.interview.materials import interview_materials
                    materials = interview_materials(rv, payload['research_thread_id'])
                elif source_kind == 'research' and rv.get('workflow', {}).get('mode') == 'review_search_report':
                    materials = validate_materials({k: rv[k] for k in ('report_markdown', 'sources')} |
                                                  {'research_thread_id': payload['research_thread_id']})
                else:
                    raise ValueError('Неподдерживаемый исходный Workflow для Chat.')
                with open_memory_store(str(self.settings.memory_db)) as store:
                    binding = {'user_id': user, 'thread_id': thread, 'store_path': str(self.settings.memory_db), 'store_id': store_identity(store)}
                seed = {**materials, 'chat_settings': {'version': 'web-1', 'user_id': user,
                    'research_thread_id': payload['research_thread_id'], 'research_checkpoint_id': payload['research_checkpoint_id'],
                    'research_title': rv['normalized_topic'], 'material_mode': source_kind},
                    'memory_binding': binding, 'memory_snapshot': {}, 'memory_diagnostics': {}, 'messages': [],
                    'summary': '', 'summarized_through': None, 'context_budget': asdict(ContextBudget()),
                    'answer': '', 'status': 'ready', 'model_calls': 0, 'tool_calls_used': 0, 'stop_requested': False}
                await self.client.threads.update_state(thread, seed, as_node='finish')
                values = seed
                input_data = {'incoming_question': payload.get('question', 'Объясни главное в отчёте.')}
            elif operation == 'ask':
                if state.get('next') or values.get('status') == 'answering':
                    raise HTTPException(409, 'Предыдущий вопрос не завершён. Сначала Resume.')
                input_data = {'incoming_question': payload['question']}
            elif operation == 'resume':
                if not state.get('next'):
                    raise HTTPException(409, 'Thread уже завершён; повторный Run не нужен.')
                if state.get('interrupts') or any(t.get('interrupts') for t in state.get('tasks', [])):
                    raise HTTPException(409, 'Требуется решение Review, а не Resume.')
                if state.get('next') == ['begin_turn'] and values.get('status') == 'answering':
                    # A native enqueue after a failed run was rejected by begin_turn.
                    # Resume the prior unfinished parent task, preserving its child namespace.
                    history = await self.client.threads.get_history(thread, limit=100)
                    from research_assistant.web.recovery import pending_checkpoint
                    checkpoint = pending_checkpoint(history, values)
                    if checkpoint is None:
                        raise HTTPException(409, 'Не найден Checkpoint незавершённого вопроса.')
            else:
                raise ValueError('Неизвестная операция Run.')
            info = await self.owned(user, thread)
            if info['metadata']['kind'] == 'chat':
                if values.get('chat_settings', {}).get('version') != 'web-1':
                    raise ValueError('Несовместимая версия серверного Chat.')
                style = payload.get('assistant', 'brief')
                choices = {v['style']: v['id'] for v in await self.assistants()}
                if style not in choices:
                    raise ValueError('Выберите brief или detailed.')
                assistant = choices[style]
                selected = await self.client.assistants.get(assistant)
                # Native runtime retains Thread config across Assistants. Explicitly use
                # the SELECTED Assistant's actual server config for this Run's context.
                response_style = selected['config']['configurable']['response_style']
                context = {'user_id': user, 'thread_id': thread, 'store_path': str(self.settings.memory_db),
                           'response_style': response_style}
            self.journal.bind_run(user, request_id, thread, None)
            run = await self.client.runs.create(thread, assistant, input=input_data, command=command,
                context=context, checkpoint_id=checkpoint, multitask_strategy='reject',
                stream_mode=['updates', 'custom'] if assistant == 'interview' else ['updates', 'messages'], stream_subgraphs=True, stream_resumable=True,
                metadata={'user_id': user, 'request_id': request_id, 'ra_web': 1},
                config={'recursion_limit': 30, 'max_concurrency': 2})
            self.journal.bind_run(user, request_id, thread, run['run_id'])
            return {'thread_id': thread, 'run_id': run['run_id']}

    async def branch(self, user, thread, checkpoint, operation, plan=None):
        if (await self.owned(user, thread))['metadata'].get('kind') != 'research':
            raise ValueError('Fork поддерживается только для Research.')
        from research_assistant.time_travel import branch_update
        data = await self.state(user, thread, checkpoint)
        update = branch_update(data['values'], tuple(data['next']), data.get('tasks', []),
                               operation=operation, new_plan=plan)
        update['workflow']['branch']['checkpoint_id'] = checkpoint
        # JSON representation of Overwrite is not needed: branching is before any search.
        update['search_batches'] = []
        result = await self.client.threads.update_state(thread, update, as_node='generate_plan', checkpoint_id=checkpoint)
        return {'thread_id': thread, **result}

    def memory(self, user, operation, data):
        validate_user_id(user)
        with open_memory_store(str(self.settings.memory_db)) as store:
            if operation == 'get':
                return {'profile': get_profile(store, user), 'notes': list_notes(store, user)}
            if operation == 'profile':
                return update_profile(store, user, data)
            if operation == 'reset':
                reset_profile(store, user)
            elif operation == 'add':
                return {'id': save_note(store, user, data)}
            elif operation == 'update':
                return update_note(store, user, data['id'], data['patch'])
            elif operation == 'delete':
                delete_note(store, user, data['id'])
            elif operation == 'retrieve':
                found = retrieve_memory(store, user, data['question'])
                return {'notes': [{'id': n['id'], 'reason': n['reason']} for n in found['notes']]}
            elif operation not in ('reset',):
                raise ValueError('Неизвестная операция памяти.')
            return {'ok': True}
