"""Loopback-only BFF: owner checks, SDK Runs, safe projections, no CLI execution."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from urllib.parse import urlparse
import httpx
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, StreamingResponse, FileResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from research_assistant.server_settings import load_server_settings
from research_assistant.user_memory import MemoryError
from research_assistant.chat_errors import ChatError
from research_assistant.persistence import PersistenceError
from research_assistant.web.service import WebService
from research_assistant.web.client import EventProjection


def projection(data):
    values = data.get('values') or {}
    return {'checkpoint_id': data.get('checkpoint', {}).get('checkpoint_id'),
        'next': data.get('next', []), 'status': values.get('status', 'new'),
        'topic': values.get('normalized_topic', values.get('topic', '')),
        'plan': values.get('plan'), 'report_markdown': values.get('report_markdown', ''),
        'sources': values.get('sources', []), 'chat_settings': values.get('chat_settings'),
        'messages': [{'role': m['type'], 'text': m['content']} for m in values.get('messages', [])
                     if m.get('type') in ('human', 'ai') and not m.get('tool_calls') and isinstance(m.get('content'), str)],
        'memory_selection': values.get('memory_diagnostics', {}),
        'summary_present': bool(values.get('summary')),
        'error': any(t.get('error') for t in data.get('tasks', []))}


def create_app(settings=None):
    settings = settings or load_server_settings()
    service = WebService(settings)
    static = Path(__file__).parent / 'static'

    @asynccontextmanager
    async def lifespan(app):
        yield
        await service.client.http.client.aclose()

    async def health(request):
        return JSONResponse({'ok': True, 'mode': settings.mode})

    async def ready(request):
        async with httpx.AsyncClient(timeout=3) as client:
            (await client.get(settings.agent_url + '/ok')).raise_for_status()
        await asyncio.to_thread(service.memory, 'readiness', 'get', {})
        return JSONResponse({'ok': True, 'mode': settings.mode, 'agent_url': settings.agent_url})

    async def index(request):
        return FileResponse(static / 'index.html')

    async def api(request):
        user = request.query_params.get('user_id', '')
        from research_assistant.user_memory import validate_user_id
        validate_user_id(user)
        action = request.path_params['action']
        if request.method == 'GET':
            if action == 'threads':
                result = await service.threads(user)
            elif action == 'assistants':
                result = await service.assistants()
            elif action == 'memory':
                result = await asyncio.to_thread(service.memory, user, 'get', {})
            elif action == 'state':
                result = projection(await service.state(user, request.query_params['thread_id'], request.query_params.get('checkpoint_id')))
            elif action == 'history':
                thread = request.query_params['thread_id']
                await service.owned(user, thread)
                states = await service.client.threads.get_history(thread, limit=100)
                result = [{k: v for k, v in projection(s).items() if k in ('checkpoint_id', 'status', 'next', 'topic', 'plan', 'error')}
                          for s in states]
            elif action == 'run':
                thread = request.query_params['thread_id']
                await service.owned(user, thread)
                run = await service.client.runs.get(thread, request.query_params['run_id'])
                result = {'run_id': run['run_id'], 'status': run['status']}
            else:
                raise HTTPException(404, 'Маршрут не найден.')
        else:
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                raise HTTPException(403, 'Cross-origin запись запрещена.')
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError('Ожидается JSON object.')
            allowed = {'create_research': {'request_id', 'topic'},
                'review': {'request_id', 'thread_id', 'decision'},
                'create_chat': {'request_id', 'research_thread_id', 'research_checkpoint_id', 'question', 'assistant'},
                'ask': {'request_id', 'thread_id', 'question', 'assistant'},
                'resume': {'request_id', 'thread_id', 'assistant'},
                'branch': {'thread_id', 'checkpoint_id', 'operation', 'plan'},
                'recover': {'request_id', 'operation', 'payload'},
                'memory': {'operation', 'data'}}
            if action not in allowed or set(body) - allowed[action]:
                raise ValueError('Неизвестные поля или операция API.')
            if action == 'recover':
                result = await service.recover(user, body['request_id'], body['operation'], body['payload'])
            elif action == 'branch':
                result = await service.branch(user, body['thread_id'], body['checkpoint_id'], body['operation'], body.get('plan'))
            elif action == 'memory':
                if not isinstance(body.get('data', {}), dict) or not isinstance(body.get('operation'), str):
                    raise ValueError('Операция памяти требует operation и JSON object data.')
                result = await asyncio.to_thread(service.memory, user, body['operation'], body.get('data', {}))
            else:
                result = await service.run(user, body.pop('request_id'), action, body)
        return JSONResponse(result)

    async def report(request):
        user = request.query_params['user_id']
        state = await service.state(user, request.query_params['thread_id'], request.query_params.get('checkpoint_id'))
        values = state['values']
        if values.get('status') != 'completed':
            raise HTTPException(409, 'Отчёт ещё не готов.')
        path = Path(values['report_path']).resolve()
        if not path.is_relative_to(settings.reports) or not path.is_file():
            raise HTTPException(404, 'Файл отчёта недоступен.')
        return FileResponse(path, filename=path.name, media_type='text/markdown; charset=utf-8')

    async def events(request):
        user, thread, run = (request.query_params[k] for k in ('user_id', 'thread_id', 'run_id'))
        await service.owned(user, thread)
        await service.client.runs.get(thread, run)
        async def stream():
            projection = EventProjection()
            yield 'event: progress\ndata: ' + json.dumps({'message': 'Подключены к Run; Demo chunks синтетические' if settings.mode == 'demo' else 'Подключены к Run'}) + '\n\n'
            try:
                async for part in service.client.runs.join_stream(thread, run, cancel_on_disconnect=False,
                      last_event_id=request.headers.get('last-event-id')):
                    projected = projection.accept(part.event, part.data)
                    if projected:
                        kind, data = projected
                        yield f'event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'
                yield 'event: done\ndata: {}\n\n'
            except httpx.HTTPError:
                yield 'event: problem\ndata: ' + json.dumps({'message': 'Связь с Run прервана. Обновите состояние; вопрос повторно не отправлен.'}) + '\n\n'
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-store'})

    async def expected_error(request, exc):
        if isinstance(exc, HTTPException):
            return JSONResponse({'error': exc.detail}, status_code=exc.status_code)
        if isinstance(exc, httpx.HTTPError):
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 503
            message = {409: 'Run уже выполняется. Дождитесь завершения или обновите состояние.',
                       404: 'Ресурс не найден.'}.get(status, 'Agent Server недоступен или операция не выполнена. Обновите состояние.')
            return JSONResponse({'error': message}, status_code=status if status in (404, 409) else 503)
        return JSONResponse({'error': 'Некорректные данные запроса или ошибка локального хранилища.'
                             if isinstance(exc, (ValidationError, KeyError, MemoryError)) else str(exc)}, status_code=400)

    app = Starlette(routes=[Route('/', index), Route('/health', health), Route('/ready', ready),
        Route('/events', events), Route('/report', report), Route('/api/{action}', api, methods=['GET', 'POST']),
        Mount('/static', StaticFiles(directory=static, check_dir=False))], lifespan=lifespan,
        exception_handlers={kind: expected_error for kind in (HTTPException, httpx.HTTPError, ValueError, KeyError, MemoryError, ChatError, PersistenceError)})
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])
    return app
