# Этап 11: архитектура локального приложения

Статус: архитектура согласована пользователем 2026-10-21; реализация не начата.

## Цель и исходное состояние

Один браузерный путь Research → Review → Report → Chat с памятью, историей,
вариантами и Assistant configs. CLI сохраняется. Academy: модуль 6 полностью,
закрепление модулей 0–5. Предпосылки: State, Checkpointer, interrupt, Subgraph,
Streaming, Store. Реализация не подтверждает ручное освоение материала.

Исходный набор: 126 тестов, OK (36.938 с, Windows/Python 3.12).
Незакоммиченный этап 10 сохраняется. В langgraph.json зарегистрирован только
Demo Research. Установлены Agent Server 0.16.2, CLI 0.4.37, SDK 0.4.8,
Starlette 1.9.0 в .venv-studio. Текущий Chat требует собственного Checkpointer
и инициализации через update_state; эти границы нужно адаптировать для сервера.

## Рассмотренные варианты

1. Рекомендуется: Agent Server и небольшой отдельный BFF, статический UI без
   сборщика. SDK связывает BFF с сервером; Graph исполняется только сервером.
   Два процесса дают явную границу прикладных API и native Agent Server.
2. Custom routes внутри Agent Server: один процесс, но прикладной lifecycle и
   доступ к persistence теснее зависят от версии сервера.
3. Отдельный backend с собственным исполнением Graph: не выбран, поскольку
   создаёт второй путь выполнения и не покрывает настоящие Assistants/Double Texting.

## Процессы и интерфейсы

- Agent Server на 127.0.0.1:2024: зарегистрированные research/chat; собственные
  Threads, Runs, Checkpoints; две настоящие конфигурации Chat Assistant.
- BFF на 127.0.0.1:8080: UI, проверка владельца, прикладные операции через SDK,
  безопасная выдача отчётов, фильтрация событий, идемпотентность запросов.
- Браузер работает только с BFF. Raw API Agent Server — локальная доверенная
  поверхность для SDK/Studio; локальный user_id не является аутентификацией.
- HTML/CSS/JavaScript без Node/npm; безопасное отображение Markdown без raw HTML,
  доступные формы, адаптивная ширина, отдельная техническая диагностика.
- Новые прямые зависимости web extra: langgraph-sdk, Starlette, uvicorn;
  точные совместимые версии фиксируются после проверки установленного окружения.

## Graph и lifecycle

Переиспользуются build_graph и build_chat_graph, существующие Nodes/ToolNode,
Summary и context budget. Серверный режим Chat допускает compile без CLI saver.
Начальная серверная инициализация выполняется на границе Graph с проверкой
входа и сохранённого owner; никакой CLI subprocess на HTTP-запрос.

Chat получает серверную версию settings и неизменяемый pin Research
thread_id/checkpoint_id. При создании BFF читает именно выбранный завершённый
Checkpoint, проверяет владельца и передаёт проверенные материалы. Graph повторно
проверяет серверные settings. Клиент не задаёт пути файлов/namespace/Store.

Assistant brief/detailed меняет инструкцию ответа, а не Schema истории.
Приоритет: правила приложения → явный текущий запрос → Assistant config → Profile.
Лимиты Agent и контекста сохраняются.

## Данные и память

Серверные данные отделены от CLI и прежней Studio-практики. Предлагаемый корень:
.research_assistant/web/demo или web/live. Server checkpoints — native runtime;
Reports — подкаталог reports; Store — отдельный memory.sqlite; BFF журнал запросов
и привязок — application.sqlite. Перенос старых CLI Threads не выполняется.

Для памяти выбран явный адаптер существующего LocalMemoryStore: он сохраняет
проверенную атомарность data+receipt. Store подключается через поддерживаемый
custom Store lifecycle Agent Server, а не подменяется отдельной памятью BFF.
BFF CRUD и Graph используют одну эту базу. Если установленный runtime не позволяет
такую регистрацию, реализация останавливается на этой границе для уточнения
архитектуры; гарантии не отключаются молча.

Пути и UUID Store проверяются. Owner проверяется backend для Thread, Checkpoint,
Chat, Report и Profile/Notes. Неизвестные версии отклоняются, данные не удаляются.
Все mutation-запросы UI имеют request_id: журнал связывает его с Run ID;
после разрыва SSE браузер восстанавливает Run, а не повторяет ввод.
Неопределённый исход создания Run сверяется с сервером по metadata/request_id
до повторной попытки; глобальное exactly-once для внешних API не обещается.

## API и UI

Группы маршрутов: health/readiness; исследования и Review; Runs и SSE;
Reports; Chat и сообщения/Resume; безопасная History/Inspection и Fork/Replay;
Profile/Notes/retrieval; доступные Assistant configs.

UI: список исследований; тема и Review с редактируемым JSON Plan; отчёт и
источники; Chat с явной версией результата; Profile/Notes; история/варианты;
выбор Assistant. ID скрыты в раскрываемой диагностике. Выбранные IDs сохраняются
локально; authoritative State и история восстанавливаются сервером.

Основная стратегия Runs — явно reject. Enqueue проверяется отдельно настоящими
конкурирующими запросами; следующий вопрос обрабатывается только после завершения
первого. После ошибки первого queued-вопрос не должен затереть незавершённый Turn.
Interrupt/rollback — отдельная практика на контролируемом сценарии без файлов,
Tools с внешними эффектами и платных API. Поддержка определяется фактическими HTTP
ответами runtime. Rollback Checkpoint не отменяет уже записанные файлы/Store.

## Режимы и размещение

Demo — значение по умолчанию, явные детерминированные подмены модели/поиска,
настоящие Graph, Tools, серверный Streaming, Review, Store. Синтетические chunks
помечаются Demo и не считаются provider token streaming.
Live включается только явно, использует Polza/Tavily; без конфигурации — ошибка.
Tracing выключен. Секреты/сырые ошибки/reasoning не попадают в UI.

langgraph dev — локальная среда разработки, не production Deployment.
Файловое сохранение установленного inmem runtime найдено в исходниках, но
восстановление всех данных требует отдельного теста штатного перезапуска.
Подготовка размещения включает зависимости, env example, health/readiness,
каталоги/backup и команды Windows. Внешняя публикация, площадка, доступ и расходы
согласуются отдельно; Docker/облако автоматически не добавляются.

## План файлов и порядок реализации после согласования

1. server_graphs.py, server_context.py, server_store.py: серверный lifecycle,
   версии settings и общие фабрики; минимальные изменения chat.py/memory_tools.py.
2. demo_services.py: отдельные детерминированные сервисы для полного сценария.
3. web/service.py, web/app.py: SDK orchestration, owner, request journal,
   безопасные прикладные API и фильтр SSE.
4. web/static/: UI; package-data и отдельная серверная конфигурация.
5. scripts/: запуск/остановка и SDK-практика Assistants/Double Texting.
6. tests/: автономные проверки адаптеров, настоящий HTTP server, конкуренция,
   штатный restart. Реальный браузерный проход — отдельная проверка.
7. docs/final-walkthrough.md, README, spec: карта файлов этапов 8–11,
   ручной маршрут, Studio/SDK, результаты и остаточные критерии.

## Приёмка

Сначала сохраняется зелёный существующий набор. Затем реальный Demo HTTP:
Topic/approve/edit/cancel/Report; два Chat-вопроса; ранние события и reconnect без
дублирования; Summary; Profile между Threads; Notes CRUD; изоляция owner;
точный Research pin; History без модели; отдельные Reports после Fork;
Assistant config в Graph; reject/enqueue; ошибки API/Store; restart всех данных.
В браузере выполняются действия, а не только снимается скриншот: создание,
Review, Chat, память, история, reload, узкая ширина и длинные тексты.

Отдельные статусы: реализация, автономная проверка, ручная практика пользователя,
проверка реального провайдера, внешняя публикация. Последние два сейчас не разрешены.

## Источники и ещё не проверенные технические решения

Context7: resolve LangGraph, затем отдельные запросы о lifecycle/persistence,
SDK и Double Texting. Полученные OSS-выдержки недостаточны для доказательства
серверной поддержки; при реализации нужны тематические Platform/SDK docs и
проверка реальных маршрутов установленного сервера.

- https://docs.langchain.com/oss/python/langgraph/local-server
- https://docs.langchain.com/langsmith/double-texting
- Установленные langgraph_runtime_inmem/lifespan.py и store.py: native Store
  lifecycle и файловое сохранение найдены, restart ещё не проверен.

До реализации согласовать это предложение, затем подготовить подробный
план выполнения с точными API, проверками и критическими экспериментами.
Коммиты, push и публичный Deployment не выполняются.
