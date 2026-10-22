from copy import deepcopy
from typing import Literal, Annotated, TypedDict
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from research_assistant.schemas import NonEmptyText, Source, ReportDraft
from research_assistant.interview.schemas import InterviewQuestion, InterviewAnswer
from research_assistant.interview.sources import validate_source_ids

WORKFLOW = {'mode':'team','version':'team-web-1'}


class AnalystRole(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    analyst_id: Literal['A','B']
    name: NonEmptyText = Field(max_length=120)
    focus: NonEmptyText = Field(max_length=1000)


def default_roles() -> list[dict]:
    return [dict(analyst_id='A',name='Польза и возможности',focus='Практическая польза, применения, возможности и условия получения преимуществ.'),
            dict(analyst_id='B',name='Риски и ограничения',focus='Риски, отказы, ограничения, компромиссы и условия неприменимости.')]


def validate_roles(roles: list[dict]) -> list[dict]:
    if not isinstance(roles,list) or len(roles)!=2:
        raise ValueError('Нужны ровно две роли A и B.')
    result=[AnalystRole.model_validate(r).model_dump(mode='json') for r in roles]
    if sorted(r['analyst_id'] for r in result)!=['A','B']:
        raise ValueError('Нужны уникальные analyst_id A и B.')
    return sorted(result,key=lambda r:r['analyst_id'])


class Approve(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action: Literal['approve']


class Cancel(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action: Literal['cancel']


class Edit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action: Literal['edit']
    roles: list[AnalystRole]


decision_adapter=TypeAdapter(Annotated[Approve|Cancel|Edit,Field(discriminator='action')])


class WorkerResult(BaseModel):
    model_config=ConfigDict(extra='forbid')
    analyst_id: Literal['A','B']
    role: AnalystRole
    focus: NonEmptyText
    transcript: list[dict]
    questions: list[InterviewQuestion]
    answers: list[InterviewAnswer]
    search_queries: list[str]
    sources: list[Source]
    report_draft: ReportDraft
    limitations: list[str]
    progress: list[dict]

    @model_validator(mode='after')
    def complete(self):
        if self.role.analyst_id!=self.analyst_id or self.focus!=self.role.focus:
            raise ValueError('Результат не соответствует роли.')
        if len(self.questions)!=2 or len(self.answers)!=2 or len(self.search_queries)!=2 or [r.get('round') for r in self.transcript]!=[1,2]:
            raise ValueError('Нужны два завершённых раунда.')
        ids=[f'S{i}' for i in range(1,len(self.sources)+1)]
        for index,(record,question,answer) in enumerate(zip(self.transcript,self.questions,self.answers)):
            if record.get('question')!=question.model_dump(mode='json') or record.get('answer')!=answer.model_dump(mode='json'):
                raise ValueError('Transcript не совпадает с вопросами и ответами.')
            allowed=[f'S{i}' for i,s in enumerate(self.sources,1) if index in s.section_indexes]
            validate_source_ids(record.get('source_ids'),allowed)
            validate_source_ids(answer.source_ids,record['source_ids'])
        for section in self.report_draft.sections:validate_source_ids(section.source_ids,ids)
        return self


def merge_worker_results(left: list[dict], right: list[dict]) -> list[dict]:
    indexed={}
    for raw in [*left,*right]:
        result=WorkerResult.model_validate(raw).model_dump(mode='json')
        key=result['analyst_id']
        if key in indexed and indexed[key]!=result:
            raise ValueError('Конфликт результатов одного аналитика.')
        indexed[key]=result
    return [deepcopy(indexed[k]) for k in sorted(indexed)]


class TeamState(TypedDict, total=False):
    topic: str
    clarification: str
    normalized_topic: str
    roles: list[dict]
    review_decision: str
    worker_results: Annotated[list[dict],merge_worker_results]
    sources: list[dict]
    source_mapping: dict
    source_origins: dict
    findings: list[dict]
    report_draft: dict
    report_markdown: str
    report_path: str
    workflow: dict
    status: str
    progress: list[dict]
