"""Explicit deterministic Demo calls through the real interview Graph."""
from research_assistant.interview.schemas import InterviewQuestion, InterviewAnswer
from research_assistant.schemas import ReportDraft


def demo_analyst(topic, clarification, role, transcript):
    if not transcript:
        question = f'Какие ограничения важно учитывать при исследовании «{topic}»?'
    else:
        first = transcript[0]['answer']['text'][:160]
        question = f'В первом ответе отмечено: «{first}». Как проверить этот вывод на практике?'
    return InterviewQuestion(text=question, search_query=(topic[:150] + ' ' + ('ограничения' if not transcript else 'проверка надёжности'))[:400])


def demo_expert(question, sources, allowed_ids):
    if not allowed_ids:
        return InterviewAnswer(text='Недостаточно найденных данных для обоснованного ответа. Полные страницы не читались.', source_ids=[])
    return InterviewAnswer(text='Demo: snippets указывают на необходимость проверки Checkpoints и восстановления после ошибок. '
        'Это демонстрационные материалы; полные страницы не читались.', source_ids=allowed_ids)


def demo_search(query):
    return [dict(title='Demo — материалы о надёжности', url='https://example.com/demo/interview',
                 snippet='Demo: Checkpoints сохраняют успешные шаги; незавершённый внешний вызов может повториться при Resume.')]


def demo_synthesis(topic, transcript, sources):
    return ReportDraft(title='Demo — интервью: ' + topic, sections=[dict(title='Выводы интервью',
        text='Demo: два раунда рассмотрели ограничения и проверку восстановления. '
             + ('Данных недостаточно: поиск не вернул источников.' if not sources else 'Выводы основаны на демонстрационных snippets.'),
        source_ids=[f'S{i}' for i in range(1, len(sources) + 1)])])


def demo_services():
    """Development-only delay/fault injection configured by environment, never HTTP."""
    import os
    import time
    from pathlib import Path
    delay = min(5.0, max(0.0, float(os.getenv('RA_INTERVIEW_DEMO_DELAY', '0.35'))))
    fail_once = os.getenv('RA_INTERVIEW_DEMO_FAIL_ONCE') == '1'
    data_root = Path(os.environ['RA_WEB_DATA'])
    def delayed_analyst(*args):
        time.sleep(delay)
        return demo_analyst(*args)
    def controlled_expert(*args):
        time.sleep(delay)
        # A single fault per isolated Demo data-root, survives Graph factory recreation.
        if fail_once and 'В первом ответе' in args[0]['text']:
            marker = data_root / 'interview-fault-used'
            try:
                with marker.open('x'):
                    pass
            except FileExistsError:
                pass
            else:
                raise ValueError('Demo: однократная ошибка второго ответа. Нажмите Resume.')
        return demo_expert(*args)
    return dict(analyst=delayed_analyst, expert=controlled_expert,
                summarizer=demo_synthesis, search_function=demo_search)
