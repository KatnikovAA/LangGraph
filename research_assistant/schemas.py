"""Validated, serializable research plan schemas."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ResearchSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText
    questions: list[NonEmptyText]


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText
    sections: list[ResearchSection]


class ApproveDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve"]


class EditDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["edit"]
    plan: ResearchPlan


class CancelDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["cancel"]


review_decision_adapter = TypeAdapter(Annotated[
    ApproveDecision | EditDecision | CancelDecision, Field(discriminator="action")
])
