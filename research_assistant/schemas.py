"""Validated, serializable research plan schemas."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, TypeAdapter, field_validator

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ResearchSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText
    questions: list[NonEmptyText]


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText
    sections: list[ResearchSection]


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText
    url: NonEmptyText
    snippet: str
    section_indexes: list[Annotated[int, Field(strict=True, ge=0)]]

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        HttpUrl(value)
        # Validate without canonicalizing: only exact URL strings are deduplicated.
        return value


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
