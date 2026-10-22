"""Explicit bridge from a completed, pinned Interview to existing Chat."""
from research_assistant.chat import validate_materials


def interview_materials(values: dict, research_thread_id: str) -> dict:
    if (values.get('workflow') != {'version': 'web-1', 'mode': 'interview'}
            or values.get('status') != 'completed'
            or [r.get('round') for r in values.get('transcript', [])] != [1, 2]):
        raise ValueError('Для обсуждения нужен завершённый Interview Workflow с двумя раундами.')
    return validate_materials({'research_thread_id': research_thread_id,
        'report_markdown': values.get('report_markdown'), 'sources': values.get('sources')}, allow_empty=True)
