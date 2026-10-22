"""Safe event projection. No raw State, Tool arguments or reasoning in browser streams."""
from langgraph_sdk import get_client

PROGRESS = {'validate_topic': 'Проверяем тему', 'generate_plan': 'Составляем план',
 'review_plan': 'Ожидаем решения по плану', 'prepare_search': 'Готовим поиск',
 'search_section': 'Ищем источники', 'collect_sources': 'Собираем источники',
 'generate_report': 'Готовим отчёт', 'save_report': 'Сохраняем отчёт',
 'agent': 'Формируем ответ', 'tools': 'Выполняем Tool', 'summarize': 'Обновляем Summary'}


def public_event(event, data):
    if event.split('|')[0] == 'updates' and isinstance(data, dict):
        message = next((PROGRESS[k] for k in data if k in PROGRESS), None)
        return ('progress', {'message': message}) if message else None
    # SDK messages mode is [message, metadata]; enforce agent node and text-only payload.
    if event.split('|')[0] == 'messages' and isinstance(data, list) and len(data) == 2:
        message, metadata = data
        if (isinstance(message, dict) and isinstance(metadata, dict)
                and metadata.get('langgraph_node') == 'agent'
                and message.get('type') in ('AIMessageChunk', 'ai') and not message.get('tool_calls')
                and isinstance(message.get('content'), str) and message['content']):
            return 'token', {'text': message['content']}
    return None


class EventProjection:
    """Native SDK messages/partial are cumulative; emit deltas only for agent IDs."""
    def __init__(self):
        self.allowed = set()
        self.text = {}

    def accept(self, event, data):
        if event == 'messages/metadata' and isinstance(data, dict):
            for identifier, item in data.items():
                if item.get('metadata', {}).get('langgraph_node') == 'agent':
                    self.allowed.add(identifier)
        if event == 'messages/partial' and isinstance(data, list):
            for message in data:
                identifier = message.get('id')
                content = message.get('content')
                if (identifier in self.allowed and message.get('type') == 'ai'
                        and not message.get('tool_calls') and isinstance(content, str) and content):
                    before = self.text.get(identifier, '')
                    self.text[identifier] = content
                    return 'token', {'text': content[len(before):] if content.startswith(before) else content}
        return public_event(event, data)
