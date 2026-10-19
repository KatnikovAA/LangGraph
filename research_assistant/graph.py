"""Research request state and graph, independent of the CLI."""

from collections.abc import Callable
from typing import Any, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from research_assistant.planning import PlanGenerationError, generate_research_plan
from research_assistant.schemas import ResearchPlan


class TopicInput(TypedDict):
    topic: str


class RequestState(TopicInput):
    normalized_topic: NotRequired[str]
    status: NotRequired[Literal["ready", "planned"]]
    plan: NotRequired[dict[str, Any]]


class EmptyTopicError(ValueError):
    """The topic contains no non-whitespace characters."""


def validate_topic(state: TopicInput) -> dict[str, str]:
    normalized_topic = " ".join(state["topic"].split())
    if not normalized_topic:
        raise EmptyTopicError("Тема исследования не должна быть пустой.")
    return {"normalized_topic": normalized_topic}


def prepare_request(state: RequestState) -> dict[str, Literal["ready"]]:
    return {"status": "ready"}


def build_graph(plan_generator: Callable[[str], ResearchPlan | dict] | None = None):
    """Build a compiled graph accepting only the original topic as input."""
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
    builder.add_edge("generate_plan", END)
    return builder.compile()
