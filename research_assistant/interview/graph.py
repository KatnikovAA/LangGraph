"""One Analyst, two bounded rounds, one synthesis, atomic Report."""
from langgraph.graph import START, END, StateGraph
from research_assistant.interview.schemas import InterviewState, InterviewQuestion, InterviewAnswer, validate_interview_input, ANALYST_ROLE
from research_assistant.interview.sources import merge_sources, validate_source_ids
from research_assistant.interview.progress import tracked
from research_assistant.interview.providers import ask_analyst, answer_expert, summarize_transcript
from research_assistant.schemas import ReportDraft
from research_assistant.search import search_web, validate_search_query
from research_assistant.reporting import render_report, write_report


def after_answer(state):
    return 'ask_question' if len(state['answers']) < 2 else 'summarize_interview'


def build_interview_graph(*, analyst=None, expert=None, summarizer=None, search_function=None,
                         checkpointer=None, output_dir: str):
    analyst = analyst or ask_analyst
    expert = expert or answer_expert
    summarizer = summarizer or summarize_transcript
    searcher = search_function or search_web

    def prepare(state, config):
        data = validate_interview_input(state['topic'], state.get('clarification', ''))
        workflow = state.get('workflow', {})
        if workflow and (workflow.get('mode') != 'interview' or workflow.get('version') != 'web-1'):
            raise ValueError('Несовместимый Interview Workflow.')
        if state.get('analyst_role', ANALYST_ROLE) != ANALYST_ROLE:
            raise ValueError('Для этого режима используется фиксированная роль аналитика.')
        if state.get('transcript'):
            raise ValueError('Интервью уже начато; используйте Resume.')
        return {**data, 'normalized_topic': data['topic'], 'round': 0, 'questions': [], 'answers': [],
                'transcript': [], 'search_queries': [], 'sources': [], 'round_source_ids': [],
                'limitations': [], 'status': 'interviewing', 'workflow': {'version': 'web-1', 'mode': 'interview'}}

    def ask(state, config):
        round_number = len(state['answers']) + 1
        if round_number > 2:
            raise ValueError('Лимит двух раундов исчерпан.')
        question = InterviewQuestion.model_validate(analyst(state['normalized_topic'], state['clarification'],
            state['analyst_role'], state['transcript'])).model_dump(mode='json')
        if state['questions'] and ' '.join(question['text'].casefold().split()) == ' '.join(state['questions'][0]['text'].casefold().split()):
            raise ValueError('Второй вопрос повторяет первый. Автоматического повтора нет; доступен Resume.')
        validate_search_query(question['search_query'])
        return {'round': round_number, 'questions': [*state['questions'][:round_number - 1], question],
                'search_queries': [*state['search_queries'][:round_number - 1], question['search_query']]}

    def search(state, config):
        sources, ids = merge_sources(state['sources'], searcher(state['search_queries'][-1]), state['round'])
        return {'sources': sources, 'round_source_ids': ids,
                'limitations': [*state['limitations'], *([f'Раунд {state["round"]}: поиск не вернул источников.'] if not ids else [])]}

    def answer(state, config):
        answer = InterviewAnswer.model_validate(expert(state['questions'][-1], state['sources'], state['round_source_ids'])).model_dump(mode='json')
        answer['source_ids'] = validate_source_ids(answer['source_ids'], state['round_source_ids'])
        if not state['round_source_ids']:
            answer = {'text': 'Недостаточно найденных данных для обоснованного ответа. Полные страницы не читались.', 'source_ids': []}
        transcript = {'round': state['round'], 'question': state['questions'][-1], 'answer': answer,
                      'source_ids': state['round_source_ids']}
        return {'answers': [*state['answers'][:state['round'] - 1], answer],
                'transcript': [*state['transcript'][:state['round'] - 1], transcript]}

    def summarize(state, config):
        draft = ReportDraft.model_validate(summarizer(state['normalized_topic'], state['transcript'], state['sources']))
        markdown = render_report(draft, state['sources'])
        if state['limitations']:
            markdown += '\n## Ограничения интервью\n\n' + '\n'.join(state['limitations']) + '\n'
        return {'report_draft': draft.model_dump(mode='json'), 'report_markdown': markdown, 'status': 'report_ready'}

    def save(state, config):
        thread_id = config.get('configurable', {}).get('thread_id')
        if not thread_id:
            raise ValueError('Для сохранения интервью нужен Thread ID.')
        return {'report_path': write_report(state['report_markdown'], output_dir, thread_id, artifact_id='interview'), 'status': 'completed'}

    builder = StateGraph(InterviewState)
    for name, fn in [('prepare_interview', prepare), ('ask_question', ask), ('search_sources', search),
                     ('answer_question', answer), ('summarize_interview', summarize), ('save_report', save)]:
        builder.add_node(name, tracked(name, fn))
    builder.add_edge(START, 'prepare_interview')
    builder.add_edge('prepare_interview', 'ask_question')
    builder.add_edge('ask_question', 'search_sources')
    builder.add_edge('search_sources', 'answer_question')
    builder.add_conditional_edges('answer_question', after_answer, ['ask_question', 'summarize_interview'])
    builder.add_edge('summarize_interview', 'save_report')
    builder.add_edge('save_report', END)
    return builder.compile(checkpointer=checkpointer)
