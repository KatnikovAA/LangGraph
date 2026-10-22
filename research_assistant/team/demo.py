from research_assistant.interview.schemas import InterviewQuestion, InterviewAnswer
from research_assistant.schemas import ReportDraft


def team_analyst(topic,clarification,role,transcript,*,focus=''):
    text=(f'{role}: что важно для «{topic}» с фокусом «{focus}»?' if not transcript else
          f"{role}: в ответе «{transcript[0]['answer']['text'][:160]}» что требует дополнительной проверки?")
    return InterviewQuestion(text=text,search_query=(f'{topic[:100]} {role} '+('практика' if not transcript else 'проверка'))[:400])


def team_search(query):
    risk='Риски' in query
    return [dict(title='Demo — '+('риски' if risk else 'возможности'),
        url='https://example.com/demo/team/'+('risks' if risk else 'benefits'),
        snippet='Demo: '+('Надёжность требует проверки отказов и стоимости.' if risk else 'Возможности зависят от сценария применения.'))]


def team_expert(question,sources,allowed_ids):
    risk='Риски' in question['text']
    return InterviewAnswer(text='Demo: '+('Риски требуют проверки отказов, стоимости и восстановления.' if risk else
        'Польза проявляется в подходящих сценариях; условия применения нужно проверить.'),source_ids=allowed_ids)


def team_synthesis(topic,transcript,sources):
    return ReportDraft(title='Demo — '+transcript[0]['question']['text'][:100],sections=[dict(
        title='Позиция аналитика',text=transcript[-1]['answer']['text'],source_ids=transcript[-1]['answer']['source_ids'])])


def team_report(topic,results,materials):
    sections=[dict(title='Demo — '+r['role']['name'],text=r['report_draft']['sections'][0]['text'],
                   source_ids=r['report_draft']['sections'][0]['source_ids']) for r in materials['findings']]
    sections.append(dict(title='Ограничения',text='Demo: обе позиции требуют проверки. Это роли модели, а не независимые эксперты.',source_ids=[]))
    return ReportDraft(title='Demo — команда: '+topic,sections=sections)


def demo_services():
    import os
    import time
    import threading
    from pathlib import Path
    delay=min(3,max(0,float(os.getenv('RA_TEAM_DEMO_DELAY','0.4'))))
    fail=os.getenv('RA_TEAM_DEMO_FAIL_B')=='1'
    root=Path(os.environ['RA_WEB_DATA'])
    a_summary=threading.Event()
    def analyst(*args,focus=''):
        time.sleep(delay)
        return team_analyst(*args,focus=focus)
    def summary(*args):
        result=team_synthesis(*args)
        if 'Риски' not in args[1][0]['question']['text']:a_summary.set()
        return result
    def expert(*args):
        time.sleep(delay)
        question=args[0]['text']
        if fail and 'Риски' in question and 'в ответе' in question and not (root/'team-fault-used').exists():
            if not a_summary.wait(20):raise ValueError('Demo A не завершил синтез.')
            marker=root/'team-fault-used'
            try:
                with marker.open('x'):pass
            except FileExistsError:pass
            else:raise ValueError('Demo: сбой второго ответа B. Доступен Resume.')
        return team_expert(*args)
    return dict(analyst=analyst,expert=expert,summarizer=summary,search_function=team_search,team_summarizer=team_report)
