"""Offline Research Graph for Agent Server; never opens the CLI checkpoint database."""

from pathlib import Path

from research_assistant.graph import build_graph


def demo_plan(topic: str) -> dict:
    """Return a deterministic plan from the normalized topic without a model."""
    return {'title': f'Учебный план: {topic}', 'sections': [
        {'title': 'State и Human-in-the-Loop', 'questions': ['Как меняется State после Review?']}]}


def demo_search(query: str) -> list[dict]:
    """Return synthetic source data; the URL is never fetched."""
    return [{'title': 'УЧЕБНАЯ ПОДМЕНА поиска', 'url': 'https://example.com/studio-demo',
             'snippet': 'УЧЕБНАЯ ПОДМЕНА: Review приостанавливает Graph до решения человека.'}]


def demo_report(topic: str, plan: dict, sources: list[dict]) -> dict:
    """Produce a local ReportDraft-shaped value with actual supplied source IDs."""
    return {'title': f'УЧЕБНАЯ ПОДМЕНА: {topic}', 'sections': [
        {'title': section['title'],
         'text': 'УЧЕБНАЯ ПОДМЕНА. ' + ' '.join(source['snippet'] for source in sources),
         'source_ids': [source['id'] for source in sources]}
        for section in plan['sections']]}


def create_graph(*, output_dir: str | None = None):
    """Compile without a saver: Agent Server provides async checkpoint persistence."""
    output = output_dir or str(Path(__file__).resolve().parents[1] / '.research_assistant' / 'studio' / 'reports')
    return build_graph(
        demo_plan, review=True, search=True, report=True,
        search_function=demo_search, report_generator=demo_report,
        output_dir=output, persistence='server',
    )


graph = create_graph()
