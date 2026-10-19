"""Validated, serializable research plan schemas."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ResearchSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText
    questions: list[NonEmptyText]


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NonEmptyText
    sections: list[ResearchSection]
