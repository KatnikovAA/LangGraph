"""Offline cross-process Summary and Subgraph recovery fixture."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')
from langchain_core.messages import AIMessage, ToolMessage
from research_assistant.chat import build_chat_graph, initialize_chat, ChatError
from research_assistant.chat_context import ContextBudget
from research_assistant.persistence import open_saver
from test_chat import FakeModel, materials, call

mode, db = sys.argv[1:]
thread = 'resume' if mode in ('fail', 'resume') else 'summary'
config = {'configurable': {'thread_id': thread}}
responses = ([AIMessage('', tool_calls=[call()]), ChatError('offline failure')] if mode == 'fail' else
             [AIMessage('A' * 200) for _ in range(3)])
model = FakeModel(responses)
def summary(messages, config):
    if mode == 'continue':
        assert 'Первый пересказ' in messages[0].content
        assert 'Question1' in messages[1].content
        assert 'Question0' not in messages[1].content
    return 'Новый пересказ' if mode == 'continue' else 'Первый пересказ'

with open_saver(db) as saver:
    graph = build_chat_graph(checkpointer=saver, model_factory=lambda: model, summarizer=summary,
                             context_budget=ContextBudget(summary_threshold=80, recent_turns=1))
    if mode in ('create', 'fail'):
        initialize_chat(graph, config, materials(), db)
    if mode == 'create':
        for i in range(3):
            graph.invoke({'question': f'Question{i}'}, config, durability='sync')
    elif mode == 'continue':
        graph.invoke({'question': 'Question3'}, config, durability='sync')
        assert 'Первый пересказ' not in model.contexts[0][0].content
        assert 'Новый пересказ' in model.contexts[0][0].content
    elif mode == 'fail':
        try:
            graph.invoke({'question': 'Read source'}, config, durability='sync')
        except ChatError:
            pass
        else:
            raise AssertionError('must fail')
    else:
        graph.invoke(None, config, durability='sync')
        assert sum(isinstance(m, ToolMessage) for m in model.contexts[0]) == 1
    state = graph.get_state(config).values
    print(json.dumps({'count': len(state['messages']), 'summary': state['summary'],
                      'boundary': state['summarized_through']}, ensure_ascii=False))
