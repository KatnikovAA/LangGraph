"""Manual HTTP smoke check against the offline server on localhost:2024 only.

Run after `langgraph dev`: python tests/studio_server_smoke.py
Creates three dedicated server Threads; does not access CLI data.
"""

import json
from urllib.request import Request, urlopen


def request(path: str, data: dict | None = None):
    payload = None if data is None else json.dumps(data).encode('utf-8')
    req = Request('http://127.0.0.1:2024' + path, data=payload,
                  headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=60) as response:
        return json.load(response)


def main():
    assert request('/ok')['ok']
    for action in ('approve', 'edit', 'cancel'):
        thread = request('/threads', {'metadata': {'purpose': 'studio-offline-smoke'}})
        path = '/threads/' + thread['thread_id']
        request(path + '/runs/wait', {'assistant_id': 'research',
                                     'input': {'topic': '  LangGraph Studio  '}})
        paused = request(path + '/state')
        assert paused['values']['status'] == 'planned', paused
        assert paused['values']['normalized_topic'] == 'LangGraph Studio'
        assert paused['next'] == ['review_plan'], paused
        decision = {'action': action}
        if action == 'edit':
            decision['plan'] = {'title': 'Исправленный план', 'sections': [
                {'title': 'State', 'questions': ['Как работает Resume?']}]}
        request(path + '/runs/wait', {'assistant_id': 'research', 'command': {'resume': decision}})
        final = request(path + '/state')
        assert not final['next'], final
        assert final['values']['status'] == ('cancelled' if action == 'cancel' else 'completed'), final
        if action == 'edit':
            assert final['values']['plan'] == decision['plan']
        print(f"{action}: planned -> review_plan -> {final['values']['status']}; {thread['thread_id']}")


if __name__ == '__main__':
    main()
