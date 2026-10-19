"""Research request state and graph, independent of the CLI."""

from collections.abc import Callable
from typing import Any, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import interrupt
from pydantic import ValidationError

from research_assistant.planning import PlanGenerationError, generate_research_plan
from research_assistant.schemas import EditDecision, ResearchPlan, review_decision_adapter


class TopicInput(TypedDict):
    topic: str


class RequestState(TopicInput):
    normalized_topic: NotRequired[str]
    status: NotRequired[Literal["ready", "planned", "approved", "cancelled"]]
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


def review_plan(state: RequestState) -> dict[str, Any]:
    """Pause without side effects; validate the resume value before applying it."""
    decision = interrupt({"kind": "review_plan", "plan": state["plan"]})
    validated = review_decision_adapter.validate_python(decision)
    if validated.action == "cancel":
        return {"status": "cancelled"}
    if isinstance(validated, EditDecision):
        return {"plan": validated.plan.model_dump(mode="json"), "status": "approved"}
    return {"status": "approved"}


def build_graph(
    plan_generator: Callable[[str], ResearchPlan | dict] | None = None,
    *, review: bool = False, checkpointer: BaseCheckpointSaver | None = None,
):
    """Build a compiled graph accepting only the original topic as input."""
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
        builder.add_edge("review_plan", END)
    else:
        builder.add_edge("generate_plan", END)
    return builder.compile(checkpointer=checkpointer)
