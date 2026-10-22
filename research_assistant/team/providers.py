from research_assistant.interview.providers import structured_call
from research_assistant.interview.sources import source_context
from research_assistant.schemas import ReportDraft


def generate_team_report(topic: str, results: list[dict], materials: dict) -> ReportDraft:
    return structured_call(ReportDraft,
        'Составь общий отчёт на русском по двум аналитическим позициям. Рассмотри обе роли, '
        'существенные различия, ограничения и неопределённость. Не выдумывай согласие. '
        'Роли — вызовы модели, не независимые человеческие эксперты. Мнение одной роли '
        'не объявляй проверенным фактом. Используй только предоставленные выводы и snippets. '
        'Цитируй глобальные source_ids из данных; URL не создавай. Полные страницы не читались.',
        {'topic':topic,'findings':materials['findings'],
         'sources':source_context(materials['sources'],[f'S{i}' for i in range(1,len(materials['sources'])+1)])})
