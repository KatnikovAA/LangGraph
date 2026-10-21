"""Research request state and graph, independent of the CLI."""

import operator
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Send, interrupt
from pydantic import ValidationError

from research_assistant.planning import PlanGenerationError, generate_research_plan
from research_assistant.schemas import EditDecision, ResearchPlan, Source, review_decision_adapter
from research_assistant.search import SearchError, search_web, validate_search_query
from research_assistant.reporting import ReportError, generate_report_draft, render_report, write_report


class TopicInput(TypedDict):
    topic: str
    workflow: NotRequired[dict[str, Any]]


class RequestState(TopicInput):
    normalized_topic: NotRequired[str]
    status: NotRequired[Literal["ready", "planned", "approved", "cancelled", "sources_found", "no_sources", "report_ready", "completed"]]
    plan: NotRequired[dict[str, Any]]
    sources: NotRequired[list[dict[str, Any]]]
    report_markdown: NotRequired[str]
    report_path: NotRequired[str]


MAX_CONCURRENCY = 2


class SearchWorkerInput(TypedDict):
    section_index: int
    query: str


class SearchBatch(TypedDict):
    section_index: int
    results: list[dict[str, Any]]


class SearchState(RequestState):
    search_jobs: NotRequired[list[SearchWorkerInput]]
    search_batches: Annotated[list[SearchBatch], operator.add]


class EmptyTopicError(ValueError):
    """The topic contains no non-whitespace characters."""


def validate_topic(state: TopicInput) -> dict[str, str]:
    normalized_topic = " ".join(state["topic"].split())
    if not normalized_topic:
        raise EmptyTopicError("Тема исследования не должна быть пустой.")
    return {"normalized_topic": normalized_topic}


def prepare_request(state: RequestState) -> dict[str, Literal["ready"]]:
    return {"status": "ready"}


def review_plan(state: RequestState) -> dict[str, Any]:
    """Pause without side effects; validate the resume value before applying it."""
    decision = interrupt({"kind": "review_plan", "plan": state["plan"]})
    validated = review_decision_adapter.validate_python(decision)
    if validated.action == "cancel":
        return {"status": "cancelled"}
    if isinstance(validated, EditDecision):
        return {"plan": validated.plan.model_dump(mode="json"), "status": "approved"}
    return {"status": "approved"}


def route_after_review(state: RequestState) -> Literal["prepare_search", "__end__"]:
    if state["status"] == "approved":
        return "prepare_search"
    if state["status"] == "cancelled":
        return END
    raise ValueError("Маршрутизация после review требует approved или cancelled.")


def prepare_search(state: SearchState) -> dict[str, list[SearchWorkerInput]]:
    """Validate every query before dispatching any external request."""
    if state["status"] != "approved":
        raise ValueError("Поиск требует утверждённый план.")
    plan = ResearchPlan.model_validate(state["plan"])
    jobs = [SearchWorkerInput(section_index=index,
                              query=" ".join([state["normalized_topic"], section.title, *section.questions]))
            for index, section in enumerate(plan.sections)]
    for job in jobs:
        validate_search_query(job['query'])
    return {'search_jobs': jobs}


def dispatch_search(state: SearchState) -> list[Send] | Literal['collect_sources']:
    jobs = state['search_jobs']
    return [Send('search_section', dict(job)) for job in jobs] if jobs else 'collect_sources'


def search_section(
    state: SearchWorkerInput,
    search_function: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, list[SearchBatch]]:
    """One task, one search call, one immutable partial state update."""
    searcher = search_function if search_function is not None else search_web
    results = searcher(state['query'])
    if not isinstance(results, list):
        raise SearchError("Поиск вернул некорректные данные: ожидается список источников.")
    validated = []
    for item in results:
        if not isinstance(item, dict):
            raise SearchError("Поиск вернул некорректный источник: ожидается объект.")
        try:
            source = Source.model_validate({**item, 'section_indexes': [state['section_index']]})
        except ValidationError as error:
            raise SearchError("Источник не прошёл проверку title, HTTP(S) URL или snippet.") from error
        validated.append(source.model_dump(mode='json'))
    return {'search_batches': [SearchBatch(section_index=state['section_index'], results=validated)]}


def collect_sources(state: SearchState) -> dict[str, Any]:
    """Fan-in: completeness first, then deterministic order and exact URL merge."""
    expected = [job['section_index'] for job in state['search_jobs']]
    batches = state.get('search_batches', [])
    indexes = [batch['section_index'] for batch in batches]
    if (any(type(index) is not int for index in indexes)
            or len(indexes) != len(expected) or sorted(indexes) != sorted(expected)):
        raise SearchError('Получен неполный или повторяющийся набор результатов поиска по разделам.')
    sources: dict[str, dict[str, Any]] = {}
    for batch in sorted(batches, key=lambda item: item['section_index']):
        index = batch['section_index']
        for item in batch['results']:
            if item['url'] in sources:
                indexes = sources[item['url']]['section_indexes']
                if index not in indexes:
                    indexes.append(index)
            else:
                sources[item['url']] = {**item, 'section_indexes': [index]}
    return {'sources': list(sources.values()), 'status': 'sources_found' if sources else 'no_sources'}


def build_graph(
    plan_generator: Callable[[str], ResearchPlan | dict] | None = None,
    *, review: bool = False, checkpointer: BaseCheckpointSaver | None = None,
    search: bool = False, search_function: Callable[[str], list[dict[str, Any]]] | None = None,
    report: bool = False, output_dir: str | None = None,
    report_generator: Callable | None = None,
    break_before_search: bool = False,
    persistence: Literal['caller', 'server'] = 'caller',
):
    """Compile workflow; CLI owns its saver, Agent Server injects its own persistence."""
    if persistence not in ('caller', 'server'):
        raise ValueError('Неизвестный режим Persistence.')
    if persistence == 'server' and checkpointer is not None:
        raise ValueError('Режим server не допускает собственный checkpointer.')
    if search and not review:
        raise ValueError("Режим search требует review и утверждение плана.")
    if report and not (review and search):
        raise ValueError("Режим report требует review и search.")
    if break_before_search and not (report and (checkpointer is not None or persistence == 'server')):
        raise ValueError('Static Breakpoint требует полного Research Workflow и Checkpointer.')
    resolved_output = str(Path(output_dir or 'reports').resolve())
    if review and checkpointer is None and persistence != 'server':
        raise ValueError("Режим review требует checkpointer для паузы и продолжения.")
    builder = StateGraph(SearchState if search else RequestState, input_schema=TopicInput)
    builder.add_node("validate_topic", validate_topic)
    builder.add_node("prepare_request", prepare_request)

    def generate_plan(state: RequestState) -> dict[str, Any]:
        generator = plan_generator if plan_generator is not None else generate_research_plan
        raw_plan = generator(state["normalized_topic"])
        try:
            plan = ResearchPlan.model_validate(raw_plan)
        except ValidationError as error:
            raise PlanGenerationError("Модель вернула некорректную структуру плана исследования.") from error
        return {"plan": plan.model_dump(mode="json"), "status": "planned"}

    builder.add_node("generate_plan", generate_plan)
    builder.add_edge(START, "validate_topic")
    builder.add_edge("validate_topic", "prepare_request")
    builder.add_edge("prepare_request", "generate_plan")
    if review:
        builder.add_node("review_plan", review_plan)
        builder.add_edge("generate_plan", "review_plan")
        if search:
            def run_search(state: SearchWorkerInput) -> dict[str, Any]:
                return search_section(state, search_function)

            builder.add_node('prepare_search', prepare_search)
            builder.add_node('search_section', run_search, input_schema=SearchWorkerInput)
            builder.add_node('collect_sources', collect_sources)
            builder.add_conditional_edges('review_plan', route_after_review,
                                          {'prepare_search': 'prepare_search', END: END})
            builder.add_conditional_edges('prepare_search', dispatch_search,
                                          ['search_section', 'collect_sources'])
            builder.add_edge('search_section', 'collect_sources')
            if report:
                def generate_report(state: RequestState) -> dict[str, Any]:
                    sources = state['sources']
                    data = [{'id': f'S{i}', 'title': item['title'], 'snippet': item['snippet']}
                            for i, item in enumerate(sources, 1)]
                    generator = report_generator if report_generator is not None else generate_report_draft
                    draft = generator(state['normalized_topic'], state['plan'], data)
                    return {'report_markdown': render_report(draft, sources), 'status': 'report_ready'}

                def save_report(state: RequestState, config: RunnableConfig) -> dict[str, Any]:
                    if state.get('workflow') and state['workflow'].get('output_dir') != resolved_output:
                        raise ReportError('Каталог Report не совпадает с сохранёнными настройками Workflow.')
                    path = write_report(state['report_markdown'], resolved_output,
                                        config['configurable']['thread_id'],
                                        artifact_id=state.get('workflow', {}).get('artifact_id'))
                    return {'report_path': path, 'status': 'completed'}

                def route_after_search(state: RequestState) -> str:
                    return 'generate_report' if state['status'] == 'sources_found' else END

                builder.add_node('generate_report', generate_report)
                builder.add_node('save_report', save_report)
                builder.add_conditional_edges('collect_sources', route_after_search,
                                              {'generate_report': 'generate_report', END: END})
                builder.add_edge('generate_report', 'save_report')
                builder.add_edge('save_report', END)
            else:
                builder.add_edge("collect_sources", END)
        else:
            builder.add_edge("review_plan", END)
    else:
        builder.add_edge("generate_plan", END)
    return builder.compile(checkpointer=checkpointer,
                           interrupt_before=['prepare_search'] if break_before_search else None
                           ).with_config({'max_concurrency': MAX_CONCURRENCY})
