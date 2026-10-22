# Архитектура

## Research

`graph.py` связывает проверку темы, генерацию плана, Review, поиск и Report.
План проверяется ResearchPlan, ответ модели — ReportDraft. Send создаёт задачу
на раздел; Reducer собирает batches, collect_sources проверяет полноту и URL.
`reporting.py` проверяет ID, экранирует текст и формирует Markdown. Атомарная
запись отделена от генерации; completed появляется только после записи.

## Interview и Team

`interview/core.py` содержит цикл Analyst → Search → Expert. Самостоятельный Graph
добавляет сохранение отчёта. Team Graph запрашивает подтверждение двух ролей,
через Send запускает Workers и объединяет результаты в общий реестр источников.
Каждый Worker сохраняет свой контекст; общий synthesis получает оба интервью.

## Chat

Chat привязан к завершённому checkpoint_id и не переключается на новый вариант
исследования автоматически. Parent хранит историю и Summary; Agent Subgraph
выполняет один вопрос с ограничением model/tool calls. ToolNode читает источники
и выполняет операции памяти. Filter/Trim не удаляют полную сохранённую историю.

## Хранение

| Контур | Ответственность |
| --- | --- |
| CLI / SqliteSaver | Research и Chat Threads |
| Agent Server | Native Threads, Checkpoints, Assistants, Runs |
| SQLite Store | Profile, Notes, owner, подтверждения операций |
| Web BFF / application.sqlite | request_id, Run IDs, восстановление запросов |
| reports | Markdown-артефакты |

user_id разделяет данные, но не заменяет аутентификацию.

## Отказы и восстановление

- Версии Workflow проверяются перед Resume; несовместимые данные сохраняются.
- Успешные Pending Writes могут использоваться после ошибки соседней задачи.
- Незавершённый внешний вызов может повториться: exactly-once не гарантируется.
- Клиент восстанавливает идентификаторы запроса до создания нового Run.
- Ошибки провайдеров санитизируются; секреты не выводятся в UI.

Порядок чтения: server_graphs.py → graph.py → interview/core.py → team/graph.py
→ chat.py → web/service.py.
