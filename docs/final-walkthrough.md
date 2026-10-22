# Research Assistant: проверка и разбор этапов 8–11

Это маршрут по приложению: сначала выполните один сценарий, затем читайте
только относящиеся к нему функции. Реализация и автономные тесты не означают,
что пользователь уже разобрал темы Academy. Live и внешнее размещение — отдельные проверки.

## Запуск на Windows PowerShell

Из корня проекта, Python 3.11 или новее (фактически проверяется 3.12.14):

```powershell
Set-Location 'F:\AI Agent\LangGraph'
py -3.12 -m venv .venv-web
.\.venv-web\Scripts\python.exe -m pip install -r requirements-web.lock -e '.[web]'
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\scripts\start-web.ps1
Start-Process 'http://127.0.0.1:8080'
```

Активация venv не обязательна. `requirements-web.lock` фиксирует фактически
используемое окружение Windows/Python 3.12, без секретов и локального editable path.
На другой версии Python совместимость отдельных бинарных пакетов проверяйте отдельно.
Первый import в новом окружении на этой Windows занял несколько минут;
startup script ждёт readiness до 600 секунд и сохраняет логи в data root.

Интерфейс: http://127.0.0.1:8080. BFF: тот же адрес `/api/*`, `/health`, `/ready`.
Настоящий Agent Server: http://127.0.0.1:2025, API reference `/docs`.
Прежний Studio server на 2024 не останавливается и его данные не используются.

Остановка:

```powershell
.\scripts\stop-web.ps1
```

Скрипт создаёт stop-файлы, Uvicorn выполняет нормальный shutdown. Он не убивает
процесс по потенциально устаревшему PID. При открытом SSE закройте страницу,
если остановка ожидает завершения соединения. Проверьте, что `/health` недоступен.

Для диагностики можно запустить два процесса в двух терминалах:

```powershell
# Терминал 1
$env:PYTHONUTF8='1'
$env:RA_WEB_MODE='demo'
.\.venv-web\Scripts\python.exe -m research_assistant.web.agent
# Терминал 2
$env:PYTHONUTF8='1'
.\.venv-web\Scripts\python.exe -m research_assistant.web
```

При использовании нестандартного RA_WEB_DATA/RA_AGENT_URL значения должны совпасть
у обоих процессов. Основные PowerShell scripts используют стандартные каталоги/порты.
Для изолированного ручного запуска BFF допускается RA_WEB_PORT; scripts фиксируют 8080.

## Что добавлялось в 8, 9, 10 и 11

| Этап | Возможность | Точки входа для чтения |
| --- | --- | --- |
| 8 | Filter/Trim, бюджет, Summary, compiled Agent Subgraph, CLI Streaming | chat_context.py: context_details/summary_context; chat.py: build_agent_subgraph/build_chat_graph; chat_streaming.py |
| 9 | Static/Dynamic Breakpoints, History, pin Research Checkpoint, Replay/Fork | graph.py: review_plan/build_graph; history.py; time_travel.py: prepare_branch/branch_update; chat_session.py |
| 10 | Profile/Collection через native Store, явные Memory Tools, receipts | user_memory.py: LocalMemoryStore/apply_tool_operation/retrieve_memory; memory_tools.py; memory_cli.py |
| 11 | Native Agent Server Research/Chat, BFF, UI, Assistants, Double Texting, deployment preparation | web/app.py → web/service.py → server_graphs.py; web/agent.py; server_store.py; scripts/ |

Пути в таблице относятся к `research_assistant/`, кроме `scripts/`.
Существующие Nodes, ToolNode, ограничение Agent и Summary переиспользуются.
Нового независимого Research/Chat Workflow для браузера нет.

## Рекомендуемый порядок чтения

1. `web/static/app.js`: `run`, `watchRun`, `refresh` — как действие связано с Run.
2. `web/app.py`: `api`, `events`, `projection` — что браузер получает и чего не получает.
3. `web/service.py`: `run`, `owned`, `state` — owner, pin, создание и Resume.
4. `server_graphs.py`: фабрики, которые регистрирует `langgraph.web.json`.
5. `graph.py`: исходный Research путь и его Review/Search fan-out/fan-in.
6. `chat.py`: Parent, Subgraph, ToolNode и ограниченный Agent Loop.
7. `chat_context.py`: контекст одного вызова, затем Summary старых целых Turns.
8. `memory_tools.py` и `user_memory.py`: Runtime Context, разрешение записи, Store.
9. `time_travel.py` и `web/service.py:branch`: общая проверка точки ветвления.

Не требуется читать все CLI-файлы, чтобы понять браузерный путь. CLI
остаётся отдельным клиентом со своими локальными базами и версиями State.

## Путь данных: UI → модель → UI

Браузер отправляет тему или вопрос с `request_id`. BFF проверяет локальный user_id,
владельца Thread и допустимые поля, резервирует операцию в journal. SDK создаёт
настоящий Run в Agent Server. Повтор того же request_id возвращает тот же Run;
после неопределённой сетевой ошибки BFF сверяет metadata и не повторяет Run вслепую.
Неподтверждённый запрос сохраняется в браузере отдельно для каждого пользователя.
Панель восстановления читает journal и связывает прежний request_id с Run;
новый вопрос блокируется до восстановления или явного снятия ожидания.
Если запрос не был зарегистрирован, повторная отправка возможна только явно,
с тем же ID. Снятие ожидания в браузере не отменяет уже запущенный серверный Run.

Фактический вызов в `WebService.run`:

```python
run = await self.client.runs.create(thread, assistant, input=input_data, command=command,
    context=context, checkpoint_id=checkpoint, multitask_strategy='reject',
    stream_mode=['updates', 'messages'], stream_subgraphs=True, stream_resumable=True,
    metadata={'user_id': user, 'request_id': request_id, 'ra_web': 1},
    config={'recursion_limit': 30, 'max_concurrency': 2})
```

Agent Server подставляет собственный Checkpointer. CLI SqliteSaver ему не передаётся.
Chat сохраняет конкретные Research thread_id/checkpoint_id и копию материалов,
поэтому последующий Fork Research не переключает старый Chat на новый отчёт.
Полный Markdown/источники берутся из сохранённого State, а не из произвольного пути клиента.

Parent Chat: begin_turn → load_memory → context_gate → optional summarize →
prepare_context → run_agent (compiled Subgraph) → finish. Subgraph:
agent → Tools → agent или finish/stop. Максимум 3 model calls и 3 Tool calls.

```python
result = subgraph.invoke(child_input, config, context=runtime.context)
```

Parent передаёт ограниченный context_history и получает только новые AI/Tool
сообщения. Полная история остаётся в Checkpoints. Summary — сокращение старой
истории для модели, не удаление истории и не пользовательский Profile.

SSE `/events` подключается к существующему Run через SDK `join_stream`.
Он не создаёт Run. `EventProjection` учитывает native `messages/metadata`, разрешает
текст только узла agent и преобразует cumulative partial messages в deltas.
Tool arguments, reasoning, Summary и Store snapshot не уходят в этот поток.
После окончания браузер читает authoritative State; предварительный текст не
считается подтверждением записи памяти. После disconnect Run продолжает работать.

Markdown renderer использует DOM text nodes, заголовки и блоки кода; HTML не
исполняется. Поддерживается простой безопасный Markdown, не весь CommonMark.
Сохранённые источники дополнительно показаны настоящими HTTP(S) ссылками.

## Память: запись и чтение

`server_store.create_store` подключён через native `store.path` в серверном config.
Agent Server владеет lifecycle этого Store. BFF CRUD открывает тот же SQLite-файл;
это одна серверная память, не отдельная UI-копия и не CLI Store.

| Namespace | Key | Назначение |
| --- | --- | --- |
| `(user_id, 'profile')` | preferences | Единственный Profile: language/style/code_language |
| `(user_id, 'notes')` | note_id | Независимые Notes: text/topic/tags/origin |
| `(user_id, 'memory_operations')` | hash | Receipt сохранённого Tool Call |

MemoryContext задаётся backend, модель не выбирает user_id/namespace/path.
`memory_access` сверяет user_id, Thread, путь и UUID Store. Валидация схем и
разрешение записи по текущему явному запросу сохранены. Примеры запросов:
«Запомни: ...», «Измени предпочтение: отвечай на English», «Удали заметку ID».
Prefix matching намеренно ограничен; формулировка без поддержанного префикса
может не разрешить Memory Tool. Через вкладку памяти CRUD доступен явно без модели.

Атомарная запись из `apply_tool_operation`:

```python
store.batch([PutOp(namespace, key, value), PutOp(receipt_ns, identifier, result)])
```

LocalMemoryStore добавляет rollback неудачной SQLite transaction. Повтор сохранённого
Tool Call не создаёт новую Note; удалённая Note не воскрешается от старого receipt.
Другая новая просьба с новым ID — новая операция. Это не глобальная exactly-once
гарантия платного API. Межпроцессные одновременные Profile patches могут иметь
семантику последнего записавшего; CAS и distributed transactions не добавлены.

Перед каждым вызовом Agent Profile перечитывается. Notes отбираются по совпадениям
слов длиной от трёх символов в text/topic/tags: максимум 3 Notes и 2400 JSON-символов.
Они входят в общий бюджет; при нехватке места убираются Notes и старые целые Turns.
Текущий вопрос и незавершённый Tool block не обрезаются. Диагностика показывает
ID/причины отбора и реальные статусы операций, не весь Store.

Удаление записи из Store не удаляет её прошлые копии из Chat/Checkpoints/backup.

## Ручной маршрут и ожидаемые результаты

| Действие | Ожидаемый результат | Что подтверждает |
| --- | --- | --- |
| alice → новая тема «Архитектура LangGraph» | planned, редактор Plan; Sources ещё нет | Review действительно до Search |
| Изменить название раздела, применить | Отчёт использует новый Plan | Editing State/Human Feedback |
| Другое исследование → отклонить | cancelled, без отчёта и поиска | Conditional routing |
| Скачать Markdown и открыть Source | Реальный файл UTF-8 и сохранённый URL | Persistence/Report |
| Обсудить результат, задать второй вопрос об S1 | Две Human реплики, get_source использует сохранённый snippet | История/Tools/Subgraph |
| Выбрать detailed и задать обычный вопрос | Demo ответ подробнее; diagnostic State сохраняет выбранный режим | Настоящий Assistant config |
| Отправить длинный вопрос, затем перезагрузить страницу | Тот же Thread/Run, вопрос не дублируется | Reconnect/idempotency |
| Несколько длинных Turns | В diagnostic summary_present=true, история полная | Context Management/Summary |
| Profile → English, новый Chat того же alice | Demo отвечает по-английски | Store между Threads |
| Создать/изменить/удалить Note; проверить отбор LangGraph | Изменения реально видны, отбор показывает ID/причину | Collection CRUD/retrieval |
| Переключиться на bob | Чужих Threads/Notes нет; русский default | Локальная partition/owner checks |
| History → Checkpoint planned/next review_plan → Fork | Новая версия плана; Review перед Search | Time Travel |
| Утвердить Fork, открыть старый Chat | Отдельный Report, старый pin сохранён | Изоляция артефактов/версий |
| Chat: `[demo:error-once] Проверь Resume` | Контролируемая ошибка; Resume без нового вопроса завершает Turn | Возобновление Subgraph |
| Остановить и запустить приложение | Threads/Reports/Profile/Notes остаются | Штатный server restart |

При Fork UI автоматически запускает продолжение до dynamic Review, затем ждёт
вашего подтверждения. API branch отдельно только подготавливает Checkpoint;
SDK-клиент после него создаёт Run с input=None, затем передаёт решение interrupt.
Resume также доступен во вкладке обсуждения для выбранного незавершённого Thread.
ID берите из server History,
не из CLI SQLite. Для просмотра исторического готового результата выберите его
Checkpoint, перейдите во вкладку исследования и создайте Chat именно по нему.

## Assistants и Double Texting

Assistant — серверная конфигурация одного Graph, не OpenAI Assistants API.
`WebService.assistants` создаёт стабильные Chat brief/detailed IDs через SDK.
Выбранный Assistant передаётся в `runs.create`; `load_memory` получает response_style
из Runtime Context и включает его в model context. BFF читает реальную config
выбранного Assistant и передаёт её стиль в context текущего Run: native runtime
иначе сохраняет приоритет старой Thread config при переключении Assistant.
SDK-пример показывает такое же явное применение. Приоритет:
правила приложения → явный текущий запрос → Assistant config → Profile.
Config не меняет Schema истории, лимиты Agent или правила доступа к источникам.

Практика настоящего SDK и конкурентных запросов:

```powershell
.\.venv-web\Scripts\python.exe scripts/api_examples.py
.\.venv-web\Scripts\python.exe scripts/double_texting.py
```

Вторая команда использует отдельный Graph concurrency с контролируемой задержкой,
без Store, файлов и платных вызовов. В установленном runtime реально проверены:
reject → HTTP409; enqueue → первый success, затем второй; interrupt → первый
interrupted; rollback → первый Run удалён, State второго. Основное приложение
явно использует reject. Disabled-кнопки — только удобство UI, не защита сервера.

Chat отдельно защищён от enqueue после ошибки: серверный input incoming_question
не затирает question текущего Turn; begin_turn отклоняет новый вопрос при answering.
BFF Resume находит прежний незавершённый run_agent Checkpoint и возобновляет его.
Rollback State не отменяет уже созданные файлы, Store writes или платные запросы.
Поэтому interrupt/rollback основного Chat с эффектами не предлагаются в UI.

## Studio: отдельная практика

Откройте Studio с baseUrl `http://127.0.0.1:2025`:
https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2025

Это тот же новый Agent Server; старый сервер на 2024 имеет отдельные IDs.
Studio — отдельный клиент сервера. Его UI может меняться; ниже не предполагается
наличие непроверенных кнопок. Собственная Web UI приложения проверяется отдельно.

1. Выберите зарегистрированный research и создайте Demo Thread с topic.
   На review_plan изучите State/next и interrupt payload. Продолжение через
   Command resume показано в scripts/api_examples.py и native `/docs`.
2. Для Chat сначала создайте его через приложение: оно проверяет owner,
   завершённый Research pin и seed. Затем найдите этот server Thread по ID
   из технической диагностики. Пустой raw Chat Thread не имеет нужных материалов.
3. В Graph исследуйте run_agent, а в native State с `subgraphs=True` — child State.
   Для точной текущей SDK сигнатуры: `client.threads.get_state(tid, subgraphs=True)`.
4. Streaming подтверждайте native join_stream/events; Summary и Tools отделяйте
   от пользовательского Agent текста. Синтетические Demo chunks не provider tokens.
5. Checkpoints/Fork: приложение History и SDK get_history/update_state; допустима
   только точка planned до завершения Review. Не запускайте произвольный checkpoint
   поверх готового результата без нового artifact_id.
6. Store между Threads: Profile/Note через вкладку памяти, два Chat одного alice,
   затем bob. Наличие конкретной Store-панели в текущем Studio не заявляется.
7. Assistant create/get/apply — проверяемый scripts/api_examples.py;
   четыре Double Texting стратегии — scripts/double_texting.py.

Ручной проход текущего Studio UI и понимание пользователя ещё не подтверждены.

## Persistence, backup и размещение

По умолчанию `.research_assistant/web/demo/` и `/live/` раздельны:

- `runtime/.langgraph_api/`: native dev Threads/Runs/Checkpoints/Assistants;
- `memory.sqlite`: серверный native Store с Profile/Notes/receipts;
- `application.sqlite`: request_id journal BFF;
- `reports/`: отдельные Markdown-артефакты;
- `*.log`, `processes.json`, `*.stop`: локальные эксплуатационные файлы.

CLI `.research_assistant/checkpoints.sqlite`, `.research_assistant/memory.sqlite`
и прежние Reports автоматически не переносятся. Базы/секреты/venv исключены из Git.
Не очищайте .langgraph_api ради несовместимой версии: сохраните копию и выберите
новый data directory либо восстановите прежние зависимости.

Backup: штатно остановить оба процесса, убедиться, что порты недоступны,
скопировать ВЕСЬ data root вместе с runtime, SQLite и Reports. Восстановление —
тот же абсолютный data path и совместимые версии пакетов; сохранённые path/UUID
проверяются. Перемещение Store/Reports потребует отдельной явной миграции.
Native dev persistence использует локальные pickle-файлы; не загружайте их
из недоверенного источника. Проверен штатный restart, не crash recovery/HA.
Перед native startup `web/runtime_guard.py` проверяет версии и читаемость
сохранённых pickle dicts. При несовместимости запуск останавливается до native
loader: установленный dev runtime сам мог бы удалить повреждённый cache.
Проверка реальным запуском на временных повреждённых файлах подтверждает отказ
без удаления данных. `server_logging.py` скрывает сырые ошибки провайдера,
traceback и payload; для диагностики остаются State, статусы и Run/Thread IDs.

Live запускается отдельно:

```powershell
.\scripts\stop-web.ps1
.\scripts\start-web.ps1 -Mode live
# Остановка Live:
.\scripts\stop-web.ps1 -Mode live
```

Только Agent Server читает существующий `.env` с Polza/Tavily. Отсутствие ключа
или модели прерывает startup; Demo автоматически не превращается в Live.
Live-настройка ещё не является разрешением агенту выполнить платные тесты.

Локальный `langgraph dev` не production Deployment. Для внешнего размещения
предлагается отдельно согласовать площадку Agent Server, persistent backend,
volumes, аутентификацию/авторизацию, TLS и бюджет. Текущий BFF с user selector и
native server без auth нельзя публиковать наружу. Multi-worker/distributed
idempotency, Docker, PostgreSQL/Redis и облачные ресурсы в этом этапе не создавались.

Актуальные официальные источники: [Deployment](https://docs.langchain.com/langsmith/deployment),
[Assistants](https://docs.langchain.com/langsmith/assistants),
[Double Texting](https://docs.langchain.com/langsmith/double-texting),
[Local Server](https://docs.langchain.com/oss/python/langgraph/local-server).
Перед внешним размещением условия платформы/лицензии и цены проверяются повторно.

## Проверки и границы результата

```powershell
# Прежние проверки + unit-тесты новых адаптеров; real HTTP tests по умолчанию skip
.\.venv-web\Scripts\python.exe -m unittest discover -s tests -q
# На работающем Demo:
$env:RA_HTTP_TESTS='1'
.\.venv-web\Scripts\python.exe -m unittest discover -s tests -p test_web_http.py -v
Remove-Item Env:RA_HTTP_TESTS
# Отдельно: остановка/запуск Demo, после сохранения Profile English и Note у alice
$env:RA_RESTART_TESTS='1'
.\.venv-web\Scripts\python.exe -m unittest discover -s tests -p test_web_restart.py -v
Remove-Item Env:RA_RESTART_TESTS
```

Real HTTP tests пишут только Demo test_* пользователей. Restart test сохраняет
данные существующего Demo и использует alice; перед запуском пройдите маршрут
Profile English + Note. Он не является тестом crash recovery.

Фактические итоговые результаты и открытые проверки фиксируются в spec.md.
Реальный Polza token streaming, качество Live Summary/Report, внешняя публикация,
ручная практика пользователя и полный текущий Studio UI отдельно не подтверждены.

### Фактическая автономная приёмка 2026-10-21

| Критерий задания | Доказательство |
| --- | --- |
| H1–H2: Research, approve/edit/cancel | Real HTTP tests и действия в браузере |
| H3: конкретный Report + второй вопрос | Real HTTP и браузер; старый Chat сохранил исходный pin после Fork |
| H4–H5: ранний Streaming, reconnect без дубля | HTTP SSE token до terminal Run; повторное подключение сохранило одну HumanMessage; reload UI восстановил Thread |
| H6: длинный диалог/Summary | HTTP test_long_chat_summary: 7 Human Turns, summary_present=true, полная история |
| H7–H10: Profile/изоляция/CRUD/restart | HTTP, браузерный CRUD и смена alice/bob; restart test сравнил Threads, checkpoints, сообщения, Reports, Profile/Notes, Assistants |
| H11–H12: History/Fork/pin | SDK get_history/get_state; HTTP и браузерный Fork создали отдельный Report, исходный Chat не переключился |
| H13: Assistant config | brief/detailed в новых и одном существующем Chat; SDK create/get/apply с реальными Assistant IDs |
| H14: concurrency | scripts/double_texting.py: real reject409/enqueue/interrupt/rollback; HTTP enqueue после error + Resume |
| H15: ошибки API/Store | JSON validation/owner/path/origin; контролируемая Demo ошибка + Resume; Store error sanitization; native corrupt-runtime startup отказ без удаления |
| H16: прежний CLI | Основное .venv: 149 обнаружено, 135 выполнено, 14 optional/integration skip, 40.341с, OK |

В .venv-web: 149 обнаружено, 137 выполнено, 12 integration skip, 43.396с, OK.
Отдельно запущены все 12 integration cases: HTTP — 10/10, 93.325с;
штатный restart — 1/1, 10.548с; чистая копия исходников без .env/баз — 1/1,
13.267с, включая отказ Live без конфигурации. Новое .venv-web установлено
из requirements-web.lock через uv; pip check, compileall и git diff --check успешны.
Обычные команды pip установки приведены выше; серверы также запущены из нового venv.

Browser E2E включал ввод, Edit/approve, cancel, Report/Chat, второй вопрос,
Profile, Note add/update/delete/retrieval, смену пользователя, Fork и старый pin.
Проверены viewport 375×812 и 1280×900, длинный заголовок, отсутствие горизонтального
переполнения (scrollWidth=clientWidth). Viewport override сброшен.
Изображение результата сохранено вне репозитория.

Независимый reviewer сообщил три важных замечания: recovery потерянного ответа,
сохранность несовместимого runtime, Resume по устойчивому Turn ID. Все исправлены
с regression checks. Reviewer затем прервался по лимиту; полного завершённого
повторного независимого review нет. Дополнительный self-review выявил и закрыл
неверный тип Thread ID и запрет неявного latest при null/пустом Research pin.

Текущие пределы: локальный single-process BFF/один Agent Server, последние 100
Threads/Checkpoints/Run records в отдельных представлениях и recovery lookup,
приблизительный token budget, простой безопасный Markdown. Pagination, production
auth, multi-worker/distributed journal, crash recovery и облачное размещение не
заявляются проверенными. Реальные платные вызовы, пользовательский разбор и
полная практика Studio остаются отдельными открытыми критериями.

## Термины и вопросы на понимание

| Термин | Применение здесь |
| --- | --- |
| API | HTTP контракт между браузером/BFF и SDK/Agent Server |
| Client | Браузер или Python SDK, запрашивающий операции сервера |
| Agent Server | Настоящий runtime, который регистрирует Graph и исполняет Runs |
| Thread | Сохранённая последовательность состояний/диалога; память одного исполнения |
| Run | Один запуск/продолжение Graph в Thread |
| Assistant | Конфигурация Chat Graph brief/detailed с настоящим server ID |
| Double Texting | Второй Run в ещё занятом Thread и выбранная серверная стратегия |
| Deployment | Размещение runtime, его конфигурации и persistence; dev запуск — локальная часть |

1. Почему после разрыва SSE нельзя просто повторить POST вопроса?
2. Чем checkpoint pin отличается от latest Research State?
3. Что Summary меняет во входе модели и чего не удаляет из истории?
4. Почему сохранение Profile в новом Thread не относится к Checkpointer?
5. Почему receipt должен записываться в одной transaction с Note?
6. Что останется на диске после rollback Run, который уже записал Report?
7. Как доказать, что detailed — Assistant config, а не только кнопка UI?
8. Каких механизмов не хватает локальному переключателю user_id для публикации?
