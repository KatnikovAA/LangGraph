from langgraph.graph import StateGraph, START, END
from langgraph.types import Send, interrupt
from research_assistant.interview.core import build_interview_core
from research_assistant.interview.schemas import validate_interview_input
from research_assistant.interview.progress import tracked
from research_assistant.team.schemas import TeamState, WORKFLOW, default_roles, validate_roles, decision_adapter, Edit
from research_assistant.team.worker import build_worker
from research_assistant.team.sources import collect_team_sources
from research_assistant.team.providers import generate_team_report
from research_assistant.schemas import ReportDraft
from research_assistant.reporting import render_report, write_report


def dispatch_interviews(state):
    if state['status']=='cancelled':return END
    if state['status']!='approved':raise ValueError('Сначала утвердите роли.')
    return [Send('interview_worker',{'topic':state['normalized_topic'],
        'clarification':state['clarification'],'role':role}) for role in state['roles']]


def build_team_graph(*,analyst=None,expert=None,summarizer=None,search_function=None,
                     team_summarizer=None,checkpointer=None,output_dir:str):
    core=build_interview_core(analyst=analyst,expert=expert,summarizer=summarizer,search_function=search_function)
    synthesis=team_summarizer or generate_team_report
    def prepare(state,config):
        data=validate_interview_input(state['topic'],state.get('clarification',''))
        if state.get('workflow',WORKFLOW)!=WORKFLOW:raise ValueError('Несовместимый Team Workflow.')
        if state.get('worker_results'):raise ValueError('Команда уже запущена; используйте Resume.')
        return {'topic':data['topic'],'normalized_topic':data['topic'],'clarification':data['clarification'],
            'roles':default_roles(),'worker_results':[],'workflow':dict(WORKFLOW),'status':'roles_ready','progress':[]}
    def review(state):
        decision=decision_adapter.validate_python(interrupt({'kind':'review_analysts','roles':state['roles'],'topic':state['normalized_topic']}))
        roles=validate_roles([r.model_dump(mode='json') for r in decision.roles]) if isinstance(decision,Edit) else state['roles']
        return {'roles':roles,'review_decision':decision.action,'status':'cancelled' if decision.action=='cancel' else 'approved'}
    def collect(state,config):
        results=state['worker_results']
        if [r['role'] for r in results]!=state['roles']:raise ValueError('Нужны оба результата с утверждёнными ролями.')
        return {**collect_team_sources(results),'status':'team_report_ready'}
    def report(state,config):
        materials={k:state[k] for k in ('sources','source_mapping','source_origins','findings')}
        draft=ReportDraft.model_validate(synthesis(state['normalized_topic'],state['worker_results'],materials))
        markdown=render_report(draft,state['sources'])
        limitations=[f"{r['analyst_id']}: {note}" for r in state['worker_results'] for note in r['limitations']]
        if limitations:markdown+='\n## Ограничения интервью\n\n'+'\n'.join(limitations)+'\n'
        return {'report_draft':draft.model_dump(mode='json'),'report_markdown':markdown,'status':'report_ready'}
    def save(state,config):
        thread=config.get('configurable',{}).get('thread_id')
        if not thread:raise ValueError('Нужен Thread ID.')
        return {'report_path':write_report(state['report_markdown'],output_dir,thread,artifact_id='team'),'status':'completed'}
    builder=StateGraph(TeamState)
    for name,fn in [('prepare_analysts',prepare),('collect_interviews',collect),('generate_team_report',report),('save_report',save)]:
        builder.add_node(name,tracked(name,fn))
    builder.add_node('review_analysts',review)
    builder.add_node('interview_worker',build_worker(core))
    builder.add_edge(START,'prepare_analysts');builder.add_edge('prepare_analysts','review_analysts')
    builder.add_conditional_edges('review_analysts',dispatch_interviews,['interview_worker',END])
    builder.add_edge('interview_worker','collect_interviews')
    builder.add_edge('collect_interviews','generate_team_report')
    builder.add_edge('generate_team_report','save_report');builder.add_edge('save_report',END)
    return builder.compile(checkpointer=checkpointer)
