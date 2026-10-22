"""Standalone interview wrapper with the existing persistence topology."""
from langgraph.graph import END
from research_assistant.interview.core import create_interview_builder, after_answer
from research_assistant.interview.progress import tracked
from research_assistant.reporting import write_report


def build_interview_graph(*, analyst=None, expert=None, summarizer=None, search_function=None,
                         checkpointer=None, output_dir: str):
    def save(state, config):
        thread_id = config.get('configurable', {}).get('thread_id')
        if not thread_id:
            raise ValueError('Для сохранения интервью нужен Thread ID.')
        return {'report_path': write_report(state['report_markdown'], output_dir, thread_id, artifact_id='interview'), 'status': 'completed'}
    builder = create_interview_builder(analyst=analyst, expert=expert, summarizer=summarizer,
                                      search_function=search_function)
    builder.add_node('save_report', tracked('save_report', save))
    builder.add_edge('summarize_interview', 'save_report')
    builder.add_edge('save_report', END)
    return builder.compile(checkpointer=checkpointer)
