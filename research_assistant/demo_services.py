"""Explicit deterministic Demo services; never contact a paid provider."""
import json
import re
import time
from uuid import uuid4
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from research_assistant.memory_tools import requested_operation
from research_assistant.chat_errors import ChatError

_failed_questions = set()


def demo_plan(topic):
    time.sleep(.15)
    return {'title': f'Demo: {topic}', 'sections': [
        {'title': 'Компоненты и взаимодействие', 'questions': ['Как связаны компоненты?']}]}


def demo_search(query):
    time.sleep(.2)
    return [{'title': 'Demo: сохранённый источник', 'url': 'https://docs.langchain.com/oss/python/langgraph/overview',
             'snippet': 'Demo: StateGraph связывает Nodes и Edges. Checkpointer сохраняет State, Store хранит память между Threads.'}]


def demo_report(topic, plan, sources):
    return {'title': f'Demo: {plan["title"]}', 'sections': [{'title': s['title'],
        'text': 'Детерминированный Demo-отчёт. ' + sources[0]['snippet'],
        'source_ids': [v['id'] for v in sources]} for s in plan['sections']]}


def demo_summary(messages, config):
    return 'Demo Summary: пользователь обсуждает компоненты отчёта и сохранённые источники.'


class DemoChatModel(BaseChatModel):
    @property
    def _llm_type(self):
        return 'research-assistant-explicit-demo'

    def bind_tools(self, tools, **kwargs):
        return self

    def response(self, messages):
        human = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        question = human.text
        if '[demo:error-once]' in question and human.id not in _failed_questions:
            time.sleep(.5)
            _failed_questions.add(human.id)
            raise ChatError('Demo: контролируемая ошибка. Выполните Resume без нового вопроса.')
        if isinstance(messages[-1], ToolMessage):
            return AIMessage('Demo: Tool выполнен. Результат операции доступен в диагностике; источник использован из сохранённого отчёта.')
        operation = requested_operation(question)
        if operation:
            if operation == 'save_note':
                args = {'note': {'text': question.split(':', 1)[-1].strip()[:600]}}
            elif operation == 'delete_note':
                args = {'note_id': question.split()[-1]}
            else:
                args = {'preferences': {'language': 'English' if re.search(r'english|англий', question, re.I) else 'русский'}}
            return AIMessage('', tool_calls=[{'name': operation, 'args': args, 'id': uuid4().hex}])
        if re.search('источник|source', question, re.I):
            return AIMessage('', tool_calls=[{'name': 'get_source', 'args': {'source_id': 'S1'}, 'id': uuid4().hex}])
        base = messages[0].text
        english = '"language": "English"' in base
        detailed = 'ASSISTANT_STYLE=detailed' in base
        text = ('Demo: StateGraph connects nodes and edges; checkpoints preserve thread state.' if english else
                'Demo: StateGraph связывает узлы и рёбра; Checkpointer сохраняет состояние Thread.')
        if detailed:
            text += ' Store хранит Profile и Collection между диалогами. Agent Subgraph выполняет ограниченный цикл модели и Tools.'
            text += ' Это детерминированная подмена, а не ответ провайдера. Уточняйте факты по источникам отчёта.'
        return AIMessage(text)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.response(messages))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        response = self.response(messages)
        if response.tool_calls:
            yield ChatGenerationChunk(message=AIMessageChunk('', tool_call_chunks=[
                {'name': c['name'], 'args': json.dumps(c['args']), 'id': c['id'], 'index': i}
                for i, c in enumerate(response.tool_calls)]))
        else:
            for word in response.text.split(' '):
                time.sleep(.035)
                yield ChatGenerationChunk(message=AIMessageChunk(word + ' '))
