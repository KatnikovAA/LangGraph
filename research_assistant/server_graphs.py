"""Native Agent Server entrypoints; compile without CLI persistence objects."""
import time
from typing import TypedDict
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from research_assistant.graph import build_graph
from research_assistant.chat import build_chat_graph
from research_assistant.server_settings import load_server_settings
from research_assistant.demo_services import DemoChatModel, demo_plan, demo_search, demo_report, demo_summary


def create_research_graph(config: RunnableConfig):
    settings = load_server_settings()
    return build_graph(demo_plan if settings.mode == 'demo' else None,
        review=True, search=True, report=True, persistence='server',
        output_dir=str(settings.reports),
        search_function=demo_search if settings.mode == 'demo' else None,
        report_generator=demo_report if settings.mode == 'demo' else None)


def create_chat_graph(config: RunnableConfig):
    settings = load_server_settings()
    style = config.get('configurable', {}).get('response_style', 'brief')
    if style not in ('brief', 'detailed'):
        raise ValueError('Неизвестная конфигурация Assistant.')
    return build_chat_graph(persistence='server',
        model_factory=(lambda: DemoChatModel()) if settings.mode == 'demo' else None,
        summarizer=demo_summary if settings.mode == 'demo' else None)


class ConcurrencyState(TypedDict):
    value: str


def create_concurrency_graph(config: RunnableConfig):
    """Isolated no-effects practice for all four native multitask strategies."""
    def controlled(state):
        time.sleep(2)
        return {'value': state['value']}
    return StateGraph(ConcurrencyState).add_node('controlled', controlled).add_edge(
        START, 'controlled').add_edge('controlled', END).compile()
