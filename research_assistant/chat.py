"""A separate, bounded report discussion graph with short-term thread memory."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal, NotRequired, TypedDict

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import InjectedState, ToolNode
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.runtime import Runtime
from research_assistant.memory_tools import (MemoryContext, MEMORY_TOOLS, MEMORY_TOOL_NAMES, memory_view,
    current_question, requested_operation, operation_results)
from research_assistant.user_memory import MemoryError, validate_user_id, store_identity
from openai import APIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_assistant.planning import create_model
from research_assistant.schemas import NonEmptyText, Source
from research_assistant.chat_errors import ChatError
from research_assistant.chat_context import (ContextBudget, budget_for, estimate_tokens, filter_history,
    select_context, context_details, summary_candidates, summary_context, summarize_with_model)

CHAT_VERSION = 3
MEMORY_CHAT_VERSION = 4
CHAT_MODE = 'report_chat'
MAX_MODEL_CALLS = 3
MAX_TOOL_CALLS = 3


class ChatMaterials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    research_thread_id: NonEmptyText
    report_markdown: NonEmptyText
    sources: list[Source] = Field(min_length=1)


class ChatInput(TypedDict):
    question: str


class ServerChatInput(TypedDict):
    incoming_question: str


class ChatOutput(TypedDict):
    answer: str
    status: Literal['answered', 'limited']


class ChatState(MessagesState):
    question: NotRequired[str]
    incoming_question: NotRequired[str]
    research_thread_id: str
    report_markdown: str
    sources: list[dict]
    chat_settings: dict
    context_budget: dict
    summary: str
    summarized_through: str | None
    context_history: list
    summary_pending: bool
    memory_binding: dict
    memory_snapshot: dict
    memory_diagnostics: dict
    assistant_style: str
    model_calls: int
    tool_calls_used: int
    stop_requested: bool
    answer: str
    status: Literal['ready', 'answering', 'answered', 'limited']


class AgentState(MessagesState):
    """Per-invocation messages contain only NEW AI/Tool messages, never old history."""
    report_markdown: str
    sources: list[dict]
    summary: str
    context_budget: dict
    context_history: list
    memory_binding: dict
    memory_snapshot: dict
    memory_diagnostics: dict
    assistant_style: str
    model_calls: int
    tool_calls_used: int
    stop_requested: bool
    answer: str
    status: Literal['answering', 'answered', 'limited']


def validate_materials(data: dict, *, allow_empty: bool = False) -> dict:
    try:
        if allow_empty:
            # Only server-validated Interview bindings opt in. Research keeps min_length=1.
            class InterviewChatMaterials(ChatMaterials):
                sources: list[Source]
            return InterviewChatMaterials.model_validate(data).model_dump(mode='json')
        return ChatMaterials.model_validate(data).model_dump(mode='json')
    except ValidationError as error:
        raise ChatError('Обсуждению нужен завершённый непустой Report и корректные сохранённые источники.') from error


@tool
def get_source(source_id: str, state: Annotated[dict, InjectedState]) -> str:
    """Read title, URL and snippet of a saved source S1, S2, etc. No web requests."""
    indexed = {f'S{i}': source for i, source in enumerate(state['sources'], 1)}
    source = indexed.get(source_id)
    if source is None:
        return json.dumps({'error': 'unknown_source_id', 'source_id': source_id}, ensure_ascii=False)
    return json.dumps({'source_id': source_id, **{key: source[key] for key in ('title', 'url', 'snippet')}}, ensure_ascii=False)


def validate_history(messages: list) -> None:
    """Reject malformed protocol histories before exposing them to the model."""
    pending = set()
    for message in messages:
        if isinstance(message, ToolMessage):
            if message.tool_call_id not in pending:
                raise ChatError('Некорректная история Tool Messages.')
            pending.remove(message.tool_call_id)
        elif isinstance(message, (HumanMessage, AIMessage)):
            if pending:
                raise ChatError('История содержит незавершённые Tool Calls.')
            if isinstance(message, AIMessage):
                ids = [call['id'] for call in message.tool_calls]
                if any(not identifier for identifier in ids) or len(ids) != len(set(ids)):
                    raise ChatError('Некорректные ID Tool Calls.')
                pending.update(ids)
        else:
            raise ChatError('В истории диалога допустимы только Human, AI и Tool Messages.')
    if pending:
        raise ChatError('История содержит незавершённые Tool Calls.')


def begin_turn(state: ChatState) -> dict:
    server = state.get('chat_settings', {}).get('version') == 'web-1'
    if server and state.get('status') == 'answering':
        raise ChatError('Предыдущий вопрос не завершён. Новый вопрос отклонён; используйте Resume.')
    question = state.get('incoming_question') if server else state.get('question')
    if not isinstance(question, str) or not question.strip():
        raise ChatError('Вопрос не должен быть пустым.')
    validate_materials({key: state[key] for key in ('research_thread_id', 'report_markdown', 'sources')},
                      allow_empty=server and state.get('chat_settings', {}).get('material_mode') == 'interview')
    validate_history(state.get('messages', []))
    return {'question': question, 'messages': [HumanMessage(content=question.strip())], 'model_calls': 0,
            'tool_calls_used': 0, 'stop_requested': False, 'answer': '', 'status': 'answering'}


def model_context(state: ChatState) -> list:
    catalog = [get_source, *MEMORY_TOOLS] if state.get('memory_binding') else [get_source]
    return select_context(state, [convert_to_openai_tool(tool) for tool in catalog])


def route_agent(state: AgentState) -> Literal['tools', 'stop', 'finish']:
    if state['messages'][-1].tool_calls:
        return 'stop' if state['stop_requested'] else 'tools'
    return 'finish'


def stop_agent(state: AgentState) -> dict:
    explanation = 'Достигнут лимит обсуждения одного вопроса. Уточните вопрос; дополнительные вызовы источников остановлены.'
    closed = [ToolMessage(content='Вызов не выполнен: достигнут лимит Agent Loop.', tool_call_id=call['id'],
                          name=call['name']) for call in state['messages'][-1].tool_calls]
    return {'messages': closed + [AIMessage(content=explanation)], 'answer': explanation, 'status': 'limited'}


def finish_turn(state: AgentState) -> dict:
    return {'answer': state['messages'][-1].text, 'status': 'answered'}


class AgentOutput(ChatOutput):
    messages: list
    model_calls: int
    tool_calls_used: int
    memory_diagnostics: dict


def build_agent_subgraph(model_factory=None):
    """Default checkpointer=None inherits parent; per-invocation, not per-thread memory."""
    def agent(state: AgentState, config: RunnableConfig, runtime: Runtime[MemoryContext]) -> dict:
        validate_history(state['messages'])
        # Tool errors/denials cannot be turned into a false success by another model response.
        for message in reversed(state['messages']):
            if not isinstance(message, ToolMessage):
                break
            if message.name in MEMORY_TOOL_NAMES:
                try:
                    outcome = json.loads(message.content)
                except (ValueError, TypeError):
                    outcome = {}
                if outcome.get('status') not in ('saved', 'deleted', 'already_applied'):
                    return {'messages': [AIMessage('Не все операции с памятью выполнены или подтверждены. '
                        'Проверьте явный запрос, данные и доступ к Store.')], 'stop_requested': False}
                if (outcome.get('status') == 'already_applied' and not outcome.get('present')
                        and message.name != 'delete_note'):
                    return {'messages': [AIMessage('Этот вызов памяти уже выполнялся, но запись сейчас отсутствует. '
                        'Повторное сохранение не выполнялось.')], 'stop_requested': False}
        catalog = [get_source, *MEMORY_TOOLS] if state.get('memory_binding') else [get_source]
        schema = [convert_to_openai_tool(tool) for tool in catalog]
        selected = memory_view(runtime, state.get('memory_binding'), current_question(state).content)
        context, selected = context_details({**state, 'messages': state['context_history'], 'summarized_through': None},
                                 schema, new_messages=state['messages'], memory=selected)
        try:
            model = (model_factory or create_model)().bind_tools(catalog)
            response = model.invoke(context, config=config)
        except (APIError, NotImplementedError, OutputParserException, ValidationError) as error:
            raise ChatError('Ошибка модели обсуждения. Проверьте поддержку Tool Calling (bind_tools) '
                            'у выбранной модели Польза AI, конфигурацию и доступность API. Автоповтора нет.') from error
        if not isinstance(response, AIMessage) or response.invalid_tool_calls:
            raise ChatError('Модель вернула некорректный ответ или Tool Calls; текст не интерпретируется как вызов Tool.')
        calls = response.tool_calls
        ids = [call['id'] for call in calls]
        if any(not identifier for identifier in ids) or len(ids) != len(set(ids)):
            raise ChatError('Модель вернула некорректные ID Tool Calls.')
        if not calls and not response.text.strip():
            raise ChatError('Модель вернула пустой ответ обсуждения.')
        if not calls and state.get('memory_binding'):
            requested = requested_operation(current_question(state).content)
            confirmed = any(result['tool'] == requested and result['status'] in ('saved', 'deleted', 'already_applied')
                            for result in operation_results(state['messages']))
            if requested and not confirmed:
                response = AIMessage('Запись или удаление памяти не выполнялись: модель не вызвала нужный Tool. '
                                     'Проверьте память через CLI или повторите явный запрос.')
        model_calls = state['model_calls'] + 1
        stop = bool(calls) and (model_calls >= MAX_MODEL_CALLS or state['tool_calls_used'] + len(calls) > MAX_TOOL_CALLS)
        # Do not persist SDK metadata or reuse provider message IDs across questions.
        message = AIMessage(content=response.content, tool_calls=calls)
        return {'messages': [message], 'model_calls': model_calls, 'stop_requested': stop,
                'memory_diagnostics': {'notes': [{'id': n['id'], 'reason': n['reason']} for n in selected.get('notes', [])]},
                'tool_calls_used': state['tool_calls_used'] + (len(calls) if not stop else 0)}

    builder = StateGraph(AgentState, output_schema=AgentOutput, context_schema=MemoryContext)
    builder.add_node('agent', agent)
    builder.add_node('tools', ToolNode([get_source, *MEMORY_TOOLS],
                     handle_tool_errors='Некорректный вызов Tool. Проверьте допустимые аргументы.'))
    builder.add_node('stop', stop_agent)
    builder.add_node('finish', finish_turn)
    builder.add_edge(START, 'agent')
    builder.add_conditional_edges('agent', route_agent, ['tools', 'stop', 'finish'])
    builder.add_edge('tools', 'agent')
    builder.add_edge('stop', END)
    builder.add_edge('finish', END)
    return builder.compile()  # Inherit saver; each parent task gets its own Namespace.


def validate_context_state(state: dict) -> None:
    budget = budget_for(state)
    summary, boundary = state.get('summary'), state.get('summarized_through')
    if (not isinstance(summary, str) or (boundary is not None and not isinstance(boundary, str))
            or bool(summary) != (boundary is not None)
            or (summary and estimate_tokens([SystemMessage(summary)]) > budget.summary_tokens)):
        raise ChatError('Некорректные сохранённые Summary или граница пересказа.')
    filter_history(state['messages'], boundary)


def build_chat_graph(*, checkpointer=None, model_factory=None, summarizer=None, context_budget=None, store=None, persistence='cli'):
    """Persistent Parent history -> bounded context -> compiled per-question Agent Subgraph."""
    if persistence not in ('cli', 'server') or (persistence == 'server' and checkpointer is not None):
        raise ValueError('Некорректный режим Persistence Chat.')
    if checkpointer is None and persistence != 'server':
        raise ValueError('Chat Graph требует checkpointer.')
    budget = context_budget or ContextBudget()
    subgraph = build_agent_subgraph(model_factory)

    def load_memory(state: ChatState, config: RunnableConfig, runtime: Runtime[MemoryContext]) -> dict:
        binding = state.get('memory_binding')
        if binding and binding.get('thread_id') != config['configurable']['thread_id']:
            raise MemoryError('Runtime Context не соответствует Chat Thread.')
        return {'memory_snapshot': memory_view(runtime, binding, state['question']),
                'assistant_style': (runtime.context.response_style if isinstance(runtime.context, MemoryContext)
                                    and runtime.context.response_style else
                    config.get('metadata', {}).get('response_style', config.get('configurable', {}).get('response_style', '')))}

    def context_gate(state: ChatState) -> dict:
        validate_context_state(state)
        model_context(state)  # Reject mandatory Report/current question BEFORE any model, including Summary.
        return {'summary_pending': bool(summary_candidates(state))}

    def route_context(state: ChatState) -> Literal['summarize', 'prepare_context']:
        return 'summarize' if summary_candidates(state) else 'prepare_context'

    def summarize(state: ChatState, config: RunnableConfig) -> dict:
        messages, selected = summary_context(state, summary_candidates(state))
        summary_config = {**config, 'tags': [*config.get('tags', []), 'summary']}
        text = (summarizer or summarize_with_model)(messages, summary_config)
        if (not isinstance(text, str) or not text.strip()
                or estimate_tokens([SystemMessage(text.strip())]) > budget_for(state).summary_tokens):
            raise ChatError('Summary пустое или превышает --summary-budget; история и граница не изменены.')
        if not selected[-1].id:
            raise ChatError('У сообщения границы Summary отсутствует ID.')
        # Both values commit in ONE checkpoint update, never before successful generation.
        return {'summary': text.strip(), 'summarized_through': selected[-1].id}

    def prepare_context(state: ChatState) -> dict:
        catalog = [get_source, *MEMORY_TOOLS] if state.get('memory_binding') else [get_source]
        messages, memory = context_details(state, [convert_to_openai_tool(t) for t in catalog])
        return {'context_history': messages[1:], 'memory_snapshot': memory}

    def run_agent(state: ChatState, config: RunnableConfig, runtime: Runtime[MemoryContext]) -> dict:
        # Parent -> child: plain context_history; reducer messages starts EMPTY per question.
        child_input = {key: state[key] for key in ('report_markdown', 'sources', 'summary', 'context_budget', 'context_history')}
        child_input.update(messages=[], model_calls=0, tool_calls_used=0, stop_requested=False,
                           answer='', status='answering', memory_binding=state.get('memory_binding', {}),
                           memory_diagnostics={}, assistant_style=state.get('assistant_style', ''),
                           memory_snapshot=state.get('memory_snapshot', {}))
        result = subgraph.invoke(child_input, config, context=runtime.context)
        result['memory_diagnostics'] = {**result.get('memory_diagnostics', {}),
                                        'operations': operation_results(result['messages'])}
        # Child -> parent: ONLY new AI/Tool messages, with checkpoint-stable IDs on Resume.
        return {key: result[key] for key in ('messages', 'answer', 'status', 'model_calls', 'tool_calls_used', 'memory_diagnostics')}

    builder = StateGraph(ChatState, input_schema=ServerChatInput if persistence == 'server' else ChatInput,
                         output_schema=ChatOutput, context_schema=MemoryContext)
    builder.add_node('begin_turn', begin_turn)
    builder.add_node('load_memory', load_memory)
    builder.add_node('context_gate', context_gate)
    builder.add_node('summarize', summarize)
    builder.add_node('prepare_context', prepare_context)
    builder.add_node('run_agent', run_agent)
    builder.add_node('finish', lambda state: {})
    builder.add_edge(START, 'begin_turn')
    builder.add_edge('begin_turn', 'load_memory')
    builder.add_edge('load_memory', 'context_gate')
    builder.add_conditional_edges('context_gate', route_context)
    builder.add_edge('summarize', 'prepare_context')
    builder.add_edge('prepare_context', 'run_agent')
    builder.add_edge('run_agent', 'finish')
    builder.add_edge('finish', END)
    graph = builder.compile(checkpointer=checkpointer, store=store).with_config({'max_concurrency': 2, 'recursion_limit': 30})
    # Construction defaults are used only when seeding a NEW chat; resumed state is authoritative.
    graph.context_budget_defaults = asdict(budget)
    return graph


def initialize_chat(graph, config: dict, data: dict, db: str, *, user_id=None, store_path=None) -> None:
    research_checkpoint_id = data.get('research_checkpoint_id')
    data = {key: value for key, value in data.items() if key != 'research_checkpoint_id'}
    data = validate_materials(data)
    settings = {'version': CHAT_VERSION, 'mode': CHAT_MODE, 'thread_id': config['configurable']['thread_id'],
                'research_thread_id': data['research_thread_id'], 'checkpoint_db': str(Path(db).resolve()),
                'research_checkpoint_id': research_checkpoint_id}
    binding = {}
    if user_id is not None:
        validate_user_id(user_id)
        if not store_path or graph.store is None:
            raise MemoryError('Для Chat с памятью нужен отдельный Store.')
        binding = {'user_id': user_id, 'store_path': str(Path(store_path).resolve()),
                   'store_id': store_identity(graph.store),
                   'thread_id': config['configurable']['thread_id']}
        settings = {**settings, **binding, 'version': MEMORY_CHAT_VERSION}
    # Seed a fresh Chat Thread without an API call; the next invoke starts a new question.
    if graph.get_state(config).values:
        raise ChatError('Chat Thread уже существует; создание поверх сохранённой истории запрещено.')
    graph.update_state(config, {**data, 'chat_settings': settings, 'messages': [], 'status': 'ready',
                                'summary': '', 'summarized_through': None,
                                'context_budget': graph.context_budget_defaults,
                                'memory_binding': binding, 'memory_snapshot': {},
                                'memory_diagnostics': {},
                                'answer': '', 'model_calls': 0, 'tool_calls_used': 0, 'stop_requested': False}, as_node='finish')
