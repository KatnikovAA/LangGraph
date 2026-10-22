# Interview Web Interface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if the user selects delegation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать этап 12: два раунда интервью в существующем UI, настоящий прогресс, Report, Resume и обсуждение результата.

**Architecture:** Новый пакет `research_assistant/interview/` содержит поведение режима. Существующий Agent Server исполняет отдельный Graph `interview`; BFF фильтрует события и сохраняет текущие owner/idempotency/checkpoint гарантии. UI подключает модули интервью к текущей форме и Report/Chat.

**Tech Stack:** Python, LangGraph 1.2.16, Agent Server 0.16.2, SDK 0.4.8, Pydantic, текущие Polza/Tavily, Starlette и vanilla JS/CSS. Новых пакетов не планируется.

**Spec:** `docs/superpowers/specs/2026-10-22-interview-design.md`, раздел этапа 12 в `spec.md`, полное пользовательское задание A–I в чате.

## Global Constraints

- Основной пакет: `research_assistant/interview/`; тесты: `tests/interview/` с `__init__.py`.
- Этап 13, Team, Fan-out и Review аналитиков исключены.
- Обычный успешный путь: 5 model calls, 2 поиска. Никаких скрытых retries.
- Источники объединяются по точному URL; S1/S2/... стабильны во всём интервью.
- Expert использует snippets; URL и ссылки строит код, source_ids проверяются.
- Chat привязан к конкретному завершённому Checkpoint; Memory и Assistants сохраняют поведение.
- Сохраняются синяя sidebar, светлый canvas, типографика, отступы и компоненты.
- Отдельная Demo-среда на проверенных свободных портах с отдельным data-root.
- Существующие Live и Demo серверы не останавливать и не перенастраивать.
- Live использует текущие Polza/Tavily; платные вызовы запрещены без отдельного разрешения. Tracing выключен.
- Commit/push, Deployment и изображения-шпаргалки в репозитории запрещены заданием.
- Реализация не подтверждает практику и понимание пользователя.
- Существующее изменение spec.md сохранить. Статус «в работе» поставить при начале реализации; завершение — только по фактической проверке критериев.

## Review Focus

- Невалидная тема/уточнение/Workflow не должны создавать частично принятый запрос или позволять задавать output_dir через браузер.
- Первый поиск с пустым результатом и второй с результатами не должны приводить к ложным ссылкам или неверной оценке ограничений.
- Разрыв SSE между завершением Node и Checkpoint не должен показывать ошибочный completed или вечный running.
- Исторический checkpoint другого Workflow, пользователя или незавершённой ветки не должен становиться источником Chat.
- Переключение Thread/пользователя при открытом SSE не должно подмешивать старые события и материалы в новый экран.

## Структура и порядок

Новые файлы пакета: `__init__.py`, `schemas.py`, `sources.py`, `providers.py`,
`graph.py`, `progress.py`, `demo.py`, `materials.py`, `README.md`,
`static/interview.js`, `static/interview.css`.
Существующие файлы подключаются в задачах ниже. Новую логику держать в пакете,
не копировать Search, Reporting, Chat, Memory. Тесты используют unittest.
Все команды ниже выполнять из корня через `.venv-web/Scripts/python.exe`.
Перед изменением библиотечного API получить актуальные тематические Context7 docs
и проверить установленный API; сетевых provider calls для проверки не делать.

### Task 1: State, Transcript и реестр источников

**Files:** Create `research_assistant/interview/{__init__,schemas,sources}.py`,
`tests/interview/{__init__,test_schemas_sources}.py`; Modify `spec.md` (статус).

**Interfaces:**
- `InterviewQuestion`: text, search_query; `InterviewAnswer`: text, source_ids.
- `InterviewState`: topic, clarification, analyst_role, round, questions, answers,
  search_queries, sources, round_source_ids, transcript, report_draft,
  report_markdown, report_path, workflow, status, progress, limitations.
- `validate_interview_input(topic: str, clarification: str) -> dict` нормализует
  ввод, назначает фиксированную роль «Технический аналитик»; extra/неверные типы отклоняются.
- `merge_sources(existing: list[dict], results: list[dict], round_number: int) -> tuple[list[dict], list[str]]`
  использует существующий Source, добавляет новые URL в конец и объединяет section_indexes.
- `validate_source_ids(ids: list[str], allowed_ids: list[str]) -> list[str]` отклоняет неизвестные ID.

- [ ] Написать test_invalid_input_and_workflow: пустая тема и non-string clarification отклоняются; системные поля не принимаются от формы.
- [ ] Написать test_registry_stability: URL A,B затем B,C дают S1=A,S2=B,S3=C; вариант URL со слешем остаётся отдельным по текущему правилу; исходные данные не мутируют.
- [ ] Написать test_empty_then_nonempty_sources и test_unknown_ids_rejected: пустой раунд не резервирует фиктивные ID; S999 отклоняется.
- [ ] Запустить `-m unittest discover -s tests/interview -p test_schemas_sources.py -v`; подтвердить ошибки до реализации.
- [ ] Реализовать перечисленные интерфейсы, строгие схемы, фиксированный Workflow mode=interview/version=web-1.
- [ ] Повторить тесты: все проходят; отметить результат в рабочем журнале плана.

### Task 2: Providers, ограниченный Graph, Demo и Resume

**Files:** Create `research_assistant/interview/{providers,graph,demo}.py`,
`tests/interview/{test_graph,test_providers}.py`.

**Interfaces:**
- `ask_analyst(topic: str, clarification: str, role: str, transcript: list[dict]) -> InterviewQuestion`.
- `answer_expert(question: dict, sources: list[dict], allowed_ids: list[str]) -> InterviewAnswer`.
- `summarize_transcript(topic: str, transcript: list[dict], sources: list[dict]) -> ReportDraft`.
- `build_interview_graph(*, analyst=None, expert=None, summarizer=None, search_function=None, checkpointer=None, output_dir: str)` возвращает compiled Graph.
- Demo-функции имеют те же сигнатуры; второй вопрос включает содержательную опору на первый ответ.
- Nodes имеют имена из дизайна; after_answer(state) выбирает ask_question при одном ответе, summarize_interview при двух.

- [ ] Написать test_two_rounds_and_budget: ровно 2 Analyst + 2 Expert + 1 synthesis, 2 поиска; второй Analyst получает первый ответ; prepare не вызывает модель.
- [ ] Написать test_empty_sources_and_malformed_output: максимум два раунда при пустых поисках, честные ограничения, отсутствие вымышленных ссылок; неверные схемы и ID останавливают Node.
- [ ] Написать test_failed_second_answer_resume: с Checkpointer ошибка второго Expert сохраняет первый раунд; invoke(None) повторяет незавершённый ответ, без повтора успешного поиска/вопроса и без дубликатов Transcript.
- [ ] Написать test_report_write_retry: ошибка записи после синтеза не повторяет synthesis; повтор save_report пишет в тот же путь, один итоговый файл.
- [ ] Написать provider tests с fake transport/model: отдельные system/user сообщения, source_ids вместо URL, max_retries=0 текущего create_model, один structured invoke на роль; секреты не входят в State/ошибки.
- [ ] Запустить `-m unittest discover -s tests/interview -p 'test_*.py' -v`, подтвердить failure новых тестов.
- [ ] Реализовать Graph и providers через существующий create_model/search_web/render_report/write_report. Ответы/вопросы обновлять по раунду; ReportDraft сразу рендерить, второго report generator не вызывать.
- [ ] Реализовать Demo с явно помеченными источниками; пустые данные и ограничения отражать программно в итоговом Report.
- [ ] Повторить тесты: все проходят. Платных запросов не делать.

### Task 3: Настоящие Progress Events

**Files:** Create `research_assistant/interview/progress.py`,
`tests/interview/test_progress.py`; Modify `research_assistant/interview/graph.py`.

**Interfaces:**
- Событие: node, round, execution_id, status=running|done|error, label, timestamp;
  run_id добавляется авторитетно в BFF. node/label/status — из allowlist.
- `project_progress(data: dict, run_id: str) -> dict | None` фильтрует и валидирует публичное событие.
- Обёртка Node отправляет custom running до вызова, done при успехе, безопасный error перед повторным исключением; успешный update сохраняет завершённое исполнение в progress State.

- [ ] Написать test_running_before_completion с блокируемым fake Expert: running читается, пока Expert ещё заблокирован; done отсутствует до освобождения.
- [ ] Написать test_error_is_not_done и test_execution_identity: второй раунд и Resume имеют отдельные execution_id; исключение не создаёт done.
- [ ] Написать test_projection_redacts_secrets: произвольные поля, неизвестный Node и невалидный timestamp не пересылаются; server run_id имеет приоритет.
- [ ] Запустить `-m unittest discover -s tests/interview -p test_progress.py -v`; подтвердить failure.
- [ ] Реализовать get_stream_writer/custom на фактической установленной версии. Сохранённые records содержат реальные времена, ошибки восстанавливаются по tasks/history; pending нельзя считать активным без проверки Run.
- [ ] Повторить тесты; не генерировать синтетические provider chunks.

### Task 4: Server, BFF, pin и адаптер Chat

**Files:** Create `research_assistant/interview/materials.py`,
`tests/interview/{test_web,test_materials}.py`; Modify `server_graphs.py`,
`langgraph.web.json`, `web/service.py`, `web/app.py`, `web/client.py`
(все под `research_assistant/`, кроме JSON).

**Interfaces:**
- `create_interview_graph(config: RunnableConfig)` выбирает Live или Demo и server persistence.
- `interview_materials(values: dict, research_thread_id: str) -> dict` проверяет Workflow, completed, Transcript, Report и источники, возвращает существующий validate_materials формат.
- POST `/api/create_interview`: request_id, topic, clarification. Server задаёт output_dir/role/thread_id/Workflow. Thread kind=interview, graph_id=interview.
- State projection добавляет interview данные и progress, сохраняя старые поля.
- create_chat принимает прежние research_thread_id/research_checkpoint_id, но выбирает явно проверенный адаптер по kind; неизвестный Workflow отклоняет.
- Interview runs используют stream_mode с custom, текущие strategy reject/journal/owner checks; resume выбирает interview, не research.

- [ ] Написать tests: успешное создание, payload validation до reserve, recover того же Run, неверный kind, чужой owner, concurrent reject, Resume маршрутизируется в interview.
- [ ] Написать tests: Chat pin точного завершённого Checkpoint интервью; чужой/незавершённый/неизвестный Workflow отклонён; обычный Research остаётся совместимым.
- [ ] Написать SSE tests: whitelist, авторитетный run_id, server Run failure не превращается в успешный done, connection loss оставляет возможность безопасно перечитать State.
- [ ] Запустить `-m unittest discover -s tests/interview -p 'test_*.py' -v`; подтвердить failure новых checks.
- [ ] Реализовать регистрацию и минимальные подключения; Report download сохраняет existing path containment check. UI не получает output_dir и полный Workflow.
- [ ] Повторить новые tests и `-m unittest discover -s tests -p test_web_service.py -v`; всё проходит.

### Task 5: UI и восстановление экрана

**Files:** Create `research_assistant/interview/static/{interview.js,interview.css}`,
`tests/interview/test_ui_assets.py`; Modify `web/static/{index.html,app.js}`,
`web/app.py` (static mount), `pyproject.toml` (package-data).

**Interfaces:**
- Browser module `window.InterviewUI`: `reset()`, `render(state, runStatus)`,
  `acceptProgress(event)`, `connectionLost()`; принимает только public projection.
- Отдельные DOM containers интервью; существующие render_report/download/discuss переиспользуются.
- Текущие run/recover/watchRun/select выбирают kind interview; создание, сброс,
  переключение пользователя и SSE guard очищают прежние данные и подписки.

- [ ] Написать asset tests: DOM IDs уникальны, ссылки на локальные assets разрешаются, пакет включает interview JS/CSS, режим и поля имеют labels.
- [ ] Запустить `-m unittest discover -s tests/interview -p test_ui_assets.py -v`; подтвердить failure.
- [ ] Перед UI-изменениями применить навык дизайна существующего интерфейса, сверить действующие HTML/CSS. Добавить режимы, уточнение, фиксированную роль/«2 раунда», Transcript, details источников, Nodes со стрелками и Resume.
- [ ] Подключить Progress Events, aria-live, реальные длительности; round 2 — отдельные исполнения шагов. Не склеивать вызовы модели; при неподтверждённых provider chunks показывать готовые сообщения.
- [ ] Реализовать восстановление по State и Run; guard от событий старого Thread/пользователя. Разрыв SSE переводит экран в явное disconnected/error состояние, затем refresh/reconnect без повторного POST.
- [ ] Добавить CSS на основе текущих цветов/типографики, mobile stacking, overflow-wrap и focus; никаких новых UI-пакетов.
- [ ] Повторить asset tests; browser interactions проверить в Task 6.

### Task 6: Изолированная Demo, HTTP и browser приёмка

**Files:** Create `tests/interview/test_http.py`,
`research_assistant/interview/start-demo.ps1`; Modify `tests/test_web_http.py`
только для настраиваемого test base URL с прежним default.

**Interfaces:**
- Demo launcher параметры AgentPort/WebPort/DataRoot; default кандидаты 2027/8082
  и `.research_assistant/interview-demo`, перед запуском проверка свободных портов.
- Launcher использует существующие web.agent/web entrypoints, RA_WEB_MODE=demo,
  RA_WEB_DATA, RA_AGENT_URL, RA_WEB_PORT; tracing=false. Процессы Hidden, логи/PID
  только своего data-root; не использует start-web.ps1 с фиксированными Live портами.
- HTTP tests opt-in RA_INTERVIEW_HTTP_TESTS=1 и RA_TEST_BASE_URL; требуют Demo mode.

- [ ] Написать HTTP tests: form-equivalent POST → два раунда → Report download → Chat с exact pin; повтор request_id/recover даёт тот же Run; reload — чтение без нового Run; чужой owner запрещён.
- [ ] Написать HTTP progress test с управляемой Demo задержкой: running приходит до done; все Nodes и round 2 различимы; server failure/Resume проверять через только Demo конфигурацию fault-once, недоступную HTTP payload/Live.
- [ ] Запустить launcher на свободных портах; дождаться /ready с mode=demo. Не останавливать существующие процессы; при сбое проверить только свои логи.
- [ ] Выполнить HTTP tests против отдельного Demo; пройти обычные Research/Review/Report/Chat/Memory HTTP regressions на том же изолированном адресе.
- [ ] Через browser tools пройти форму, наблюдение running, Transcript/источники, reload/reconnect с неизменными Run IDs, ошибку второго ответа/Resume, скачивание и Chat.
- [ ] Проверить широкий и узкий viewport, длинные тексты/URL, keyboard/focus, aria-live и horizontal overflow. Если инструмент не позволяет менять viewport или проверить действие — явно записать непроверенное, не объявлять browser E2E завершённым.

### Task 7: Регрессия, документация и разбор

**Files:** Create `research_assistant/interview/README.md`,
`docs/interview-walkthrough.md`; Modify корневые `README.md`, `spec.md`, этот план.

- [ ] Выполнить `-m unittest discover -s tests -v` в .venv-web; отдельно записать выполненные и skipped integration tests. При обнаружении несовместимости старого .venv проверить затронутые автономные сценарии там.
- [ ] Выполнить `-m compileall -q research_assistant tests`, `-m pip check`, `git diff --check`; проверить отсутствие новых пакетов, секретов и generated artifacts в diff.
- [ ] Провести итоговый review diff/проверок с навыком requesting-code-review выбранным способом выполнения; исправления проверять адресно. Статус независимого review указывать честно.
- [ ] Документировать фактический Graph, файлы, публичные функции и путь UI → API → Nodes → события → UI → Report → Chat; краткие реальные фрагменты, зависимости и stdlib отдельно.
- [ ] Записать точные команды Demo launcher, реальные адреса, лимиты, ограничения пустого поиска, ошибки/Resume, отсутствие exactly-once и условия provider token streaming.
- [ ] Обновить spec статус/критерии/журнал только по evidence, не отмечать Academy понимание завершённым. Сохранить лицензии и нейтральное описание.
- [ ] В финальном ответе сразу дать все 9 пунктов задания, включая Analyst/Expert/Loop/Conditional Edge/Transcript/Progress Events, порядок чтения и ручной сценарий. Без commit/push/deploy.

## Self-review плана — 2026-10-22

- A/B: Tasks 1–3 — Graph, бюджеты, роли, схемы, источники и ограничения.
- C: Task 4 — регистрация, API, тип Workflow, Report, pin/Chat и старое поведение.
- D/E/F: Tasks 3–6 — UI, события, безопасная проекция, reload/reconnect/Resume.
- G/H: Tasks 2 и 6 — Demo/Live, изоляция, fake tests, HTTP и browser приёмка.
- I: Task 7 — документация и обязательный разбор.
- Все пять Review Focus условий имеют проверки в Tasks 1/2/4/5/6.
- Типы и сигнатуры согласованы между задачами; новые зависимости и этап 13 отсутствуют.
- Метод выполнения и проверка пользователем этого плана ожидаются; реализация не начата.
