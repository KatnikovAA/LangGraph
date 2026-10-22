"""Real HTTP concurrency practice on an isolated Graph without external effects."""
import asyncio
import json
import os
import httpx
from langgraph_sdk import get_client


async def practice(url=None):
    client = get_client(url=url or os.getenv('RA_AGENT_URL', 'http://127.0.0.1:2025'), api_key=None)
    results = []
    try:
        for strategy in ('reject', 'enqueue', 'interrupt', 'rollback'):
            thread = (await client.threads.create(graph_id='concurrency'))['thread_id']
            first = await client.runs.create(thread, 'concurrency', input={'value': 'first'}, multitask_strategy='reject')
            for _ in range(100):
                if (await client.runs.get(thread, first['run_id']))['status'] == 'running':
                    break
                await asyncio.sleep(.03)
            else:
                raise AssertionError('Контрольный Run не начал выполняться.')
            try:
                second = await client.runs.create(thread, 'concurrency', input={'value': 'second'}, multitask_strategy=strategy)
                await client.runs.join(thread, second['run_id'])
                final = await client.threads.get_state(thread)
                assert final['values']['value'] == 'second', final
                try:
                    previous = (await client.runs.get(thread, first['run_id']))['status']
                except httpx.HTTPStatusError as error:
                    if error.response.status_code != 404:
                        raise
                    previous = 'deleted'
                if strategy == 'enqueue':
                    assert previous == 'success', previous
                elif strategy == 'interrupt':
                    assert previous == 'interrupted', previous
                elif strategy == 'rollback':
                    assert previous == 'deleted', previous
                else:
                    raise AssertionError('reject ошибочно принял второй активный Run')
                results.append({'strategy': strategy, 'result': 'verified', 'first': previous, 'final': 'second'})
            except httpx.HTTPStatusError as error:
                code = error.response.status_code
                if strategy == 'reject':
                    assert code == 409, code
                    await client.runs.join(thread, first['run_id'])
                    results.append({'strategy': strategy, 'result': 'verified', 'http_status': code})
                elif code in (400, 422, 501):
                    results.append({'strategy': strategy, 'result': 'unsupported', 'http_status': code})
                else:
                    raise
        return results
    finally:
        await client.http.client.aclose()


if __name__ == '__main__':
    print(json.dumps(asyncio.run(practice()), ensure_ascii=False, indent=2))
