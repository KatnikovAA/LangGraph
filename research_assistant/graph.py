"""Research request state and graph, independent of the CLI."""

from typing import Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph


class TopicInput(TypedDict):
    topic: str


class RequestState(TopicInput):
    normalized_topic: NotRequired[str]
    status: NotRequired[Literal["ready"]]


class EmptyTopicError(ValueError):
    """The topic contains no non-whitespace characters."""


def validate_topic(state: TopicInput) -> dict[str, str]:
    normalized_topic = " ".join(state["topic"].split())
    if not normalized_topic:
        raise EmptyTopicError("Тема исследования не должна быть пустой.")
    return {"normalized_topic": normalized_topic}


def prepare_request(state: RequestState) -> dict[str, Literal["ready"]]:
    return {"status": "ready"}


def build_graph():
    """Build a compiled graph accepting only the original topic as input."""
    builder = StateGraph(RequestState, input_schema=TopicInput)
    builder.add_node("validate_topic", validate_topic)
    builder.add_node("prepare_request", prepare_request)
    builder.add_edge(START, "validate_topic")
    builder.add_edge("validate_topic", "prepare_request")
    builder.add_edge("prepare_request", END)
    return builder.compile()
