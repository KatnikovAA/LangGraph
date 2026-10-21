"""Safe presentation of graph events; never print state or call invoke after stream."""

import sys
from langchain_core.messages import AIMessageChunk
from research_assistant.chat_errors import ChatError


def visible_text(chunk) -> str:
    if isinstance(chunk.content, str):
        return chunk.content
    return ''.join(block.get('text', '') for block in chunk.content
                   if isinstance(block, dict) and block.get('type') == 'text'
                   and isinstance(block.get('text'), str))


def stream_chat(graph, graph_input, config) -> dict:
    print('Готовим контекст', file=sys.stderr, flush=True)
    token_seen = False
    active_message = None
    # Default v1 format supported by installed LangGraph: (namespace, mode, payload).
    for namespace, mode, payload in graph.stream(graph_input, config, durability='sync',
                                                 stream_mode=['updates', 'messages'], subgraphs=True):
        if mode == 'updates':
            for node, update in payload.items():
                if not isinstance(update, dict):
                    continue
                if not namespace and node == 'context_gate' and update.get('summary_pending'):
                    print('\nОбновляем Summary', file=sys.stderr, flush=True)
                elif not namespace and node == 'prepare_context':
                    print('\nФормируем ответ', file=sys.stderr, flush=True)
                elif namespace and node == 'agent' and not update.get('stop_requested') and any(
                        getattr(m, 'tool_calls', []) for m in update.get('messages', [])):
                    print('\nЧитаем источник', file=sys.stderr, flush=True)
                elif namespace and node == 'tools':
                    print('\nФормируем ответ', file=sys.stderr, flush=True)
        elif mode == 'messages':
            chunk, metadata = payload
            # Whitelist agent-only chunks from a child Namespace. Summary, tool arguments,
            # reasoning blocks and non-streamed full AIMessage events are deliberately excluded.
            if (not namespace or metadata.get('langgraph_node') != 'agent'
                    or 'summary' in metadata.get('tags', []) or not isinstance(chunk, AIMessageChunk)):
                continue
            text = visible_text(chunk)
            if not text:
                continue
            if active_message != chunk.id or not token_seen:
                print('\nПредварительный текст Agent (может отличаться от итогового ответа): ',
                      end='', file=sys.stderr, flush=True)
                active_message = chunk.id
            print(text, end='', file=sys.stderr, flush=True)
            token_seen = True
    if not token_seen:
        print('\nТекстовые chunks не получены: token streaming провайдера не подтверждён. '
              'Показаны только события Graph; готовый текст не имитируется.', file=sys.stderr, flush=True)
    else:
        print(file=sys.stderr, flush=True)
    snapshot = graph.get_state(config)
    if snapshot.next or snapshot.values.get('status') not in ('answered', 'limited'):
        raise ChatError('Обсуждение не завершилось; успешный результат Streaming отсутствует.')
    return {key: snapshot.values[key] for key in ('answer', 'status')}
