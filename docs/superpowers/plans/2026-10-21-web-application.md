# Research Assistant Web Application Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution or superpowers:subagent-driven-development if the user chooses delegation. Execute task-by-task; track checkboxes.

**Goal:** Единое локальное браузерное приложение поверх настоящего Agent Server и существующих Research/Chat Graph.

**Architecture:** Agent Server 127.0.0.1:2024 исполняет Graph и управляет Checkpoints. BFF 127.0.0.1:8080 использует SDK, проверяет владельца и выдаёт UI. Custom Store сохраняет существующие атомарные операции памяти.

**Tech Stack:** Python >=3.11, LangGraph, Agent Server/SDK, Starlette/uvicorn, SQLite, HTML/CSS/JavaScript без Node/npm.

**Spec:** [Согласованная архитектура](../specs/2026-10-21-web-application-design.md), корневой spec.md и исходное задание этапа 11.

## Global Constraints

- Существующие незакоммиченные изменения этапа 10 сохраняются.
- Никаких commit, push, платных запросов или внешней публикации.
- Demo по умолчанию; Live только явно; Tracing выключен.
- CLI и серверные Threads/Store разделены; миграция не обещается.
- user_id — локальный выбор, не аутентификация; процессы слушают loopback.
- Основная стратегия Runs — явно reject.
- Существующие лимиты: максимум 3 вызова модели и 3 Tools на вопрос.
- Retrieval: максимум 3 Notes/2400 JSON-символов; память входит в context budget.
- Никаких подмен проверок: real HTTP, real Graph, real браузер; Demo chunks не provider streaming.
- Непроверенные критерии остаются открытыми; пользовательская практика учитывается отдельно.

## Review Focus

1. Потеря ответа на создание Run: повтор request_id восстанавливает тот же Run (задача 4).
2. Владелец меняется в браузере при открытом Chat: backend отклоняет доступ (задачи 3/7).
3. Report содержит HTML и опасные URL: UI не исполняет их (задача 7).
4. Первый queued Run падает посреди Tool Call: второй вопрос не затирает незавершённый Turn (задача 6).
5. Store или серверные файлы несовместимы после restart: понятная ошибка, никакого удаления (задачи 1/8).

## Файлы и границы

- research_assistant/server_settings.py: режим, разрешённые пути, версии и loopback.
- research_assistant/server_store.py: custom Store lifecycle.
- research_assistant/server_graphs.py: фабрики Research/Chat и серверная инициализация.
- research_assistant/demo_services.py: детерминированные сервисы с Demo-маркировкой.
- research_assistant/web/client.py: только SDK и перевод ожидаемых ошибок.
- research_assistant/web/journal.py: SQLite owner/request_id → Thread/Run.
- research_assistant/web/service.py: прикладные операции и pin результатов.
- research_assistant/web/app.py: Starlette routes, SSE, static, health/readiness.
- research_assistant/web/static/index.html, app.js, style.css: интерфейс без сборщика.
- langgraph.web.json, .env.web.example: отдельная конфигурация сервера.
- scripts/start-web.ps1, stop-web.ps1, api_examples.py, double_texting.py: эксплуатация и практика.
- tests/test_server_*.py, test_web_*.py, server_worker.py: unit/HTTP/process tests.
- docs/final-walkthrough.md: разбор 8–11, Studio/SDK и ручные сценарии.
- Минимально изменить chat.py, chat_context.py, memory_tools.py и при необходимости
  history.py/time_travel.py для общих операций; не копировать Workflow в web/.

## Порядок и проверки

### Task 1: Подтвердить серверный lifecycle и persistent Store

**Files:** server_settings.py, server_store.py, langgraph.web.json,
tests/test_server_lifecycle.py, tests/server_worker.py, pyproject.toml, .gitignore.

**Interfaces:** `load_server_settings() -> ServerSettings` (mode/data_root/reports/memory_db);
`create_store()` — context manager, возвращающий существующий LocalMemoryStore.
Отдельный test data_root не открывает рабочие базы.

- [ ] Получить Context7 resolve/query для Agent Server custom Store, graph factories,
  SDK и Starlette lifecycle; проверить фактические сигнатуры 0.16.2/0.4.8.
- [ ] Добавить тесты `test_custom_store_native_lifecycle`,
  `test_store_batch_rollback`, `test_cli_data_untouched`,
  `test_incompatible_store_preserved`; запустить до реализации и зафиксировать FAIL.
- [ ] Реализовать конфигурацию и `create_store()` через native `store.path`.
  Установленный langgraph_api/store.py подтверждает поддержку context manager;
  тест обязан подтвердить это настоящим startup и shutdown сервера.
- [ ] Проверить настоящий HTTP Store get/put + штатный restart; Store UUID и запись
  должны сохраниться, CLI-файлы остаться неизменными.
- [ ] Зафиксировать совместимые версии web extra и package-data. При отсутствии
  поддерживаемого lifecycle остановить зависимые задачи, описать конкретный блокер.

### Task 2: Research через настоящий Agent Server

**Files:** server_graphs.py, demo_services.py, tests/test_server_research.py.

**Interfaces:** `create_research_graph(config: RunnableConfig)` возвращает существующий
compiled Research без CLI saver; Demo/Live выбираются только server settings.

- [ ] Добавить real HTTP тесты `test_topic_review_report`, `test_edit_plan`,
  `test_cancel_no_search`, `test_live_missing_config_no_fallback`.
- [ ] Запустить новый файл unittest: до реализации FAIL, после — OK.
- [ ] Зарегистрировать research, задать workflow server mode и разрешённый output_dir.
  Demo использует детерминированные Plan/Search/Report; Live — существующие сервисы.
- [ ] Проверить interrupt: до approve Search не вызывается; Command resume использует
  тот же Thread. completed означает существующий корректный Report, не только статус.

### Task 3: Серверный Chat, pin и единая память

**Files:** server_graphs.py, chat.py, chat_context.py, memory_tools.py,
tests/test_server_chat.py, tests/test_server_memory.py.

**Interfaces:** `create_chat_graph(config: RunnableConfig)` — серверная фабрика;
`build_chat_graph(..., persistence='cli'|'server')` сохраняет CLI контракт по умолчанию.
Серверная инициализация принимает проверенные материалы с Research checkpoint pin;
Runtime Context конструируется из server-controlled settings и owner.

- [ ] Тесты до реализации: `test_server_chat_two_turns_and_pin`,
  `test_same_user_new_thread_profile`, `test_wrong_owner_denied`,
  `test_saved_tool_resume_idempotent`, `test_current_question_budget`,
  `test_summary_long_dialogue`.
- [ ] Разрешить native server Checkpointer без передачи SqliteSaver. Выделить общую
  подготовку initial Chat State, серверную версию settings отделить от CLI v3/v4.
- [ ] Передавать native server Store через Runtime, сохранять owner/path/UUID checks,
  явную авторизацию Tools и атомарную запись receipt. Не доверять binding из HTTP input.
- [ ] Demo Chat должен реально вызывать get_source и Memory Tools по сценарию;
  ошибки и chunks маркируются как Demo, Summary детерминированна и ограничена.
- [ ] Запустить новые тесты и существующие test_chat*, test_memory*: OK.

### Task 4: BFF, владельцы, request journal и безопасные API

**Files:** web/__init__.py, client.py, journal.py, service.py, app.py,
tests/test_web_service.py, tests/test_web_requests.py.

**Interfaces:** `create_app(settings: ServerSettings) -> Starlette`;
`WebService` предоставляет create_research, review, create_chat, ask, resume,
state, history, branch, report, memory и assistants;
`RequestJournal.reserve(user_id, request_id, payload_hash)` и
`RequestJournal.bind_run(user_id, request_id, thread_id, run_id)` сохраняют привязки.

- [ ] Тесты: чужой Thread/Report/Checkpoint/Notes → отказ; неизвестные ID → 404;
  повтор request_id → прежний Run; тот же ID с другим payload → 409;
  потеря ответа SDK → сверка metadata перед retry; arbitrary path → отклонение.
- [ ] Реализовать SDK client и journal с уникальным ключом (user_id,request_id).
  И создание Thread, и Run получают стабильную metadata-привязку операции;
  неопределённый исход не трактуется как разрешение создать второй Run.
- [ ] Реализовать owner checks перед каждым SDK действием и выдачей файла;
  Report определяется по проверенному State, не по пути из браузера.
- [ ] CRUD Profile/Notes использует тот же server Store через проверенные операции;
  backend не принимает произвольные namespace. Ошибки санитизируются.
- [ ] Health проверяет процесс, readiness дополнительно Agent Server и Store;
  Live readiness проверяет наличие настроек без платного вызова.
- [ ] Проверить unittest новых файлов: OK.

### Task 5: History/Fork и настоящие Assistants

**Files:** web/service.py, server_graphs.py, chat_context.py,
tests/test_server_history.py, tests/test_server_assistants.py, scripts/api_examples.py.

**Interfaces:** branch принимает Thread/checkpoint/optional Plan, возвращает новый
branch checkpoint и artifact ID; Assistant configs `brief`/`detailed` одного chat.

- [ ] Тесты: History/Inspection не вызывают модель; Fork только поддерживаемой точки;
  отдельный Report; исходный Chat сохраняет pin; Assistant config меняет model input.
- [ ] Переиспользовать валидацию и подготовку Replay/Fork из time_travel.py;
  заменить только доступ к snapshot/update_state на SDK и server settings.
- [ ] Через SDK создать/получить два настоящих Assistant, использовать их IDs в Runs.
  Реализовать приоритет application → explicit request → Assistant → Profile.
- [ ] api_examples.py покрывает create Thread, Run, State, interrupt resume,
  streaming, завершённый результат и Assistant create/get/apply.
- [ ] Запустить новые HTTP тесты: OK, Model counters для History равны нулю.

### Task 6: SSE и Double Texting

**Files:** web/app.py, web/client.py, scripts/double_texting.py,
tests/test_server_concurrency.py, tests/test_web_streaming.py.

**Interfaces:** SSE подключается к уже созданному Run; reconnect не создаёт Run.
Фильтр отдаёт только progress, разрешённый текст Agent, completion/error и Run ID.

- [ ] Тесты: событие до завершения; отсутствие reasoning/Tool args/Store snapshot;
  disconnect/reconnect → одна HumanMessage и один Run.
- [ ] Основной create Run всегда передаёт multitask_strategy='reject'.
- [ ] Два конкурирующих реальных HTTP запроса с контролируемой задержкой проверяют
  reject и enqueue; оба исхода и порядок фиксируются, кнопка UI не доказательство.
- [ ] Проверить enqueue после ошибки предыдущего Run: предыдущий Turn остаётся
  resumable, второй вопрос отклоняется понятной ошибкой без изменения истории.
- [ ] Практика interrupt/rollback выполняется на отдельном контролируемом Graph без
  Store/file effects. Неподдерживаемая стратегия фиксируется по HTTP ответу с
  инструкцией подходящей среды; результат не подменяется fake-сервером.

### Task 7: Браузерный интерфейс

**Files:** web/static/index.html, app.js, style.css, web/app.py,
tests/test_web_security.py.

**Interfaces:** UI использует только /api BFF, сохраняет выбранные IDs в localStorage,
  восстанавливает authoritative State/Run после reload.

- [ ] Применить подходящий UI skill, выбрать компактный интерфейс на русском;
  main/detail: исследования, Review/Report, Chat, память, History и Assistants.
- [ ] Реализовать loading/empty/error/paused/completed; request_id сохраняется до
  подтверждения; повторная отправка после разрыва сети не происходит автоматически.
- [ ] Реализовать safe Markdown: raw HTML не вставляется, ссылки только http/https;
  тесты `<script>`, javascript URL, длинные кодовые блоки, кавычки в Notes.
- [ ] Browser E2E: тема → edit → approve → Report → новый Chat → второй вопрос →
  Note CRUD → новый Thread того же user → чужой user → History/Fork → original Chat.
- [ ] Отдельно пройти cancel, reload во время Run, обрыв SSE, ошибки, ширину 375px,
  длинный Plan/Report. Сохранить фактические результаты; недоступность браузера
  прямо указать, не заменять E2E тестом HTML или скриншотом.

### Task 8: Перезапуск, Windows запуск и Deployment preparation

**Files:** scripts/start-web.ps1, stop-web.ps1, .env.web.example,
tests/test_server_restart.py, README.md.

- [ ] Start script запускает оба процесса скрыто, хранит PID и проверяет readiness;
  stop проверяет PID/команду процесса и штатно останавливает именно свои процессы.
  Demo явно, Live отдельным аргументом; неполная конфигурация не переключает режим.
- [ ] Штатно остановить и запустить сервер: Threads/Checkpoints/Reports/Profile/Notes
  сохраняются; новый Chat читает прежний Profile, чужой пользователь — нет.
- [ ] Проверить несовместимые данные: отказ без удаления или очистки каталогов.
- [ ] Воспроизвести установку из чистого временного checkout с web extra и Demo;
  не копировать .env и рабочие базы. Документировать точные команды Windows.
- [ ] Описать каталоги/volumes, остановку перед backup, восстановление, loopback,
  требования production auth/persistent backend; external Deployment оставить открытым.

### Task 9: Итоговая проверка и руководство

**Files:** docs/final-walkthrough.md, README.md, spec.md.

- [ ] При начале продуктовой реализации отметить этап 11 «в работе» и архитектуру
  согласованной. Обновлять чекбоксы этого плана после фактической проверки.
- [ ] Руководство: карта capability → file/function для 8/9/10/11; порядок чтения;
  UI → BFF → SDK → Graph → model/Tools → events; память и pin; реальные фрагменты.
- [ ] Для каждого ручного сценария указать ожидаемый результат и что он подтверждает;
  вопросы на понимание. Studio section использует проверенные возможности UI,
  остальное демонстрируется проверенным SDK, без смешения CLI/Server IDs.
- [ ] Запустить `python -m unittest discover -s tests -q` в CLI окружении и новый
  серверный набор в web окружении; compileall, pip check в обоих, git diff --check.
- [ ] Сверить все H.1–H.16 исходного задания с evidence HTTP/browser/restart.
  Academy coverage: реализация / автономная проверка / практика / облако отдельно.
- [ ] Выполнить итоговый review diff на owner обходы, повторные Runs, утечки секретов,
  ошибки lifecycle, незавершённые Tool Calls. Не создавать commit/push.
- [ ] Финал включает созданное, Windows команды/адрес, файлы/функции/зависимости,
  путь данных, результаты, ограничения, ссылку на walkthrough и термины API,
  Client, Agent Server, Run, Assistant, Double Texting, Deployment.

## Контроль согласованности плана

Все разделы A–K задания покрываются задачами 1–9. Реальные server capabilities
проверяются до зависимого UI. Исключения только явные: paid provider calls,
пользовательская практика и external Deployment не выдаются за завершённые.
План не требует коммитов и не назначает субагентов без выбора пользователя.
