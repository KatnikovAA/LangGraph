"""Validated interview boundaries; model output never defines source URLs."""
from typing import TypedDict
from pydantic import BaseModel, ConfigDict, Field
from research_assistant.schemas import NonEmptyText

ANALYST_ROLE = 'Технический аналитик'
WORKFLOW_MODE = 'interview'


class InterviewQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: NonEmptyText
    search_query: NonEmptyText


class InterviewAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: NonEmptyText
    source_ids: list[NonEmptyText]


class InterviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    topic: NonEmptyText = Field(max_length=2000)
    clarification: str = Field(default='', max_length=4000)


def validate_interview_input(topic: str, clarification: str) -> dict:
    data = InterviewInput(topic=topic, clarification=clarification)
    return {'topic': ' '.join(data.topic.split()), 'clarification': data.clarification.strip(),
            'analyst_role': ANALYST_ROLE}


class InterviewState(TypedDict, total=False):
    analyst_id: str
    focus: str
    topic: str
    normalized_topic: str
    clarification: str
    analyst_role: str
    round: int
    questions: list[dict]
    answers: list[dict]
    search_queries: list[str]
    sources: list[dict]
    round_source_ids: list[str]
    transcript: list[dict]
    report_draft: dict
    report_markdown: str
    report_path: str
    workflow: dict
    status: str
    progress: list[dict]
    limitations: list[str]
