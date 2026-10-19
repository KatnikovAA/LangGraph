"""Research request state and graph, independent of the CLI."""

from collections.abc import Callable
from typing import Any, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import interrupt
from pydantic import ValidationError

from research_assistant.planning import PlanGenerationError, generate_research_plan
from research_assistant.schemas import EditDecision, ResearchPlan, Source, review_decision_adapter
from research_assistant.search import SearchError, search_web, validate_search_query


class TopicInput(TypedDict):
    topic: str


class RequestState(TopicInput):
    normalized_topic: NotRequired[str]
    status: NotRequired[Literal["ready", "planned", "approved", "cancelled", "sources_found", "no_sources"]]
    plan: NotRequired[dict[str, Any]]
    sources: NotRequired[list[dict[str, Any]]]


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


def route_after_review(state: RequestState) -> Literal["search_sources", "__end__"]:
    if state["status"] == "approved":
        return "search_sources"
    if state["status"] == "cancelled":
        return END
    raise ValueError("Маршрутизация после review требует approved или cancelled.")


def search_sources(
    state: RequestState,
    search_function: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if state["status"] != "approved":
        raise ValueError("Поиск требует утверждённый план.")
    plan = ResearchPlan.model_validate(state["plan"])
    queries = [" ".join([state["normalized_topic"], section.title, *section.questions])
               for section in plan.sections]
    # Preflight all queries before spending credits on the first section.
    for query in queries:
        validate_search_query(query)
    searcher = search_function if search_function is not None else search_web
    sources: dict[str, dict[str, Any]] = {}
    for index, query in enumerate(queries):
        results = searcher(query)
        if not isinstance(results, list):
            raise SearchError("Поиск вернул некорректные данные: ожидается список источников.")
        for item in results:
            if not isinstance(item, dict):
                raise SearchError("Поиск вернул некорректный источник: ожидается объект.")
            try:
                source = Source.model_validate({**item, "section_indexes": [index]})
            except ValidationError as error:
                raise SearchError("Источник не прошёл проверку title, HTTP(S) URL или snippet.") from error
            if source.url in sources:
                indexes = sources[source.url]["section_indexes"]
                if index not in indexes:
                    indexes.append(index)
            else:
                sources[source.url] = source.model_dump(mode="json")
    return {"sources": list(sources.values()), "status": "sources_found" if sources else "no_sources"}


def build_graph(
    plan_generator: Callable[[str], ResearchPlan | dict] | None = None,
    *, review: bool = False, checkpointer: BaseCheckpointSaver | None = None,
    search: bool = False, search_function: Callable[[str], list[dict[str, Any]]] | None = None,
):
    """Build a compiled graph accepting only the original topic as input."""
    if search and not review:
        raise ValueError("Режим search требует review и утверждение плана.")
    if review and checkpointer is None:
        raise ValueError("Режим review требует checkpointer для паузы и продолжения.")
    builder = StateGraph(RequestState, input_schema=TopicInput)
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
            def run_search(state: RequestState) -> dict[str, Any]:
                return search_sources(state, search_function)

            builder.add_node("search_sources", run_search)
            builder.add_conditional_edges("review_plan", route_after_review,
                                          {"search_sources": "search_sources", END: END})
            builder.add_edge("search_sources", END)
        else:
            builder.add_edge("review_plan", END)
    else:
        builder.add_edge("generate_plan", END)
    return builder.compile(checkpointer=checkpointer)
