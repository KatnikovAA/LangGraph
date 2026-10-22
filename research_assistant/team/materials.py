from research_assistant.team.schemas import WORKFLOW
from research_assistant.team.sources import collect_team_sources
from research_assistant.chat import validate_materials
from research_assistant.schemas import ReportDraft
from research_assistant.reporting import render_report


def team_materials(values: dict,research_thread_id: str) -> dict:
    if values.get('workflow')!=WORKFLOW or values.get('status')!='completed':
        raise ValueError('Нужен завершённый Team Workflow совместимой версии.')
    material=collect_team_sources(values.get('worker_results',[]))
    if any(values.get(key)!=material[key] for key in ('sources','source_mapping','source_origins','findings')):
        raise ValueError('Некорректный общий реестр Team.')
    render_report(ReportDraft.model_validate(values.get('report_draft')),material['sources'])
    return validate_materials({'research_thread_id':research_thread_id,
        'report_markdown':values.get('report_markdown'),'sources':material['sources']},allow_empty=True)
