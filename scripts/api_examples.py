"""Native SDK practice: independent server IDs, no CLI SQLite or paid services."""
import asyncio
import json
import os
from uuid import uuid4
import httpx
from langgraph_sdk import get_client


async def main():
    # Check the actual server mode, not just the caller's environment.
    async with httpx.AsyncClient() as web:
        if (await web.get('http://127.0.0.1:8080/ready')).json().get('mode') != 'demo':
            raise RuntimeError('SDK practice requires the running Demo BFF.')
    client = get_client(url=os.getenv('RA_AGENT_URL', 'http://127.0.0.1:2025'), api_key=None)
    try:
        thread = await client.threads.create(graph_id='research', metadata={
            'user_id': 'sdk_practice', 'kind': 'research', 'title': 'SDK Demo', 'ra_web': 1})
        tid = thread['thread_id']
        run = await client.runs.create(tid, 'research', input={'topic': 'LangGraph SDK Demo'},
            multitask_strategy='reject', stream_mode=['updates'], stream_resumable=True)
        async for chunk in client.runs.join_stream(tid, run['run_id']):
            if chunk.event == 'updates':
                print('Nodes:', ', '.join(chunk.data))
        state = await client.threads.get_state(tid)
        print('Review:', state['next'])
        resumed = await client.runs.create(tid, 'research', command={'resume': {'action': 'approve'}}, multitask_strategy='reject')
        await client.runs.join(tid, resumed['run_id'])
        state = await client.threads.get_state(tid)
        assistants = []
        for style in ('brief', 'detailed'):
            assistant = await client.assistants.create('chat', name='SDK practice ' + style,
                config={'configurable': {'response_style': style}})
            assistants.append((await client.assistants.get(assistant['assistant_id']))['assistant_id'])
        # Application bootstrap pins the completed Research snapshot and validates owner.
        async with httpx.AsyncClient(timeout=30) as web:
            response = await web.post('http://127.0.0.1:8080/api/create_chat?user_id=sdk_practice', json={
                'request_id': uuid4().hex, 'research_thread_id': tid,
                'research_checkpoint_id': state['checkpoint']['checkpoint_id'], 'question': 'Объясни главное'})
            response.raise_for_status()
            chat = response.json()
        await client.runs.join(chat['thread_id'], chat['run_id'])
        chat_state = await client.threads.get_state(chat['thread_id'])
        binding = chat_state['values']['memory_binding']
        selected = await client.assistants.get(assistants[1])
        applied = await client.runs.create(chat['thread_id'], assistants[1],
            input={'incoming_question': 'Объясни подробнее'},
            context={**{k: binding[k] for k in ('user_id', 'thread_id', 'store_path')},
                     'response_style': selected['config']['configurable']['response_style']}, multitask_strategy='reject')
        await client.runs.join(chat['thread_id'], applied['run_id'])
        assert (await client.threads.get_state(chat['thread_id']))['values']['assistant_style'] == 'detailed'
        print(json.dumps({'server_thread': tid, 'status': state['values']['status'],
            'checkpoint': state['checkpoint'], 'report': state['values']['report_path'],
            'assistants': assistants, 'applied_to_chat': chat['thread_id']}, ensure_ascii=False, indent=2))
    finally:
        await client.http.client.aclose()


if __name__ == '__main__':
    if os.getenv('RA_WEB_MODE', 'demo') != 'demo':
        raise SystemExit('Практику запускайте только на Demo сервере.')
    asyncio.run(main())
