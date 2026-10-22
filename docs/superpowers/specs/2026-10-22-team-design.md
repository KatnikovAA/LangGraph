# Этап 13 — два параллельных аналитика и общий Report

Дата: 2026-10-22. Дизайн интеграции согласован пользователем в чате.
Документ фиксирует архитектуру перед implementation plan. Исходное задание A–K,
корневые AGENTS.md/spec.md и актуальные уточнения пользователя обязательны.

## Цель и границы

В существующем Web Interface пользователь выбирает «Команда аналитиков», задаёт
тему/уточнение, проверяет и при необходимости редактирует две роли, утверждает
или отменяет запуск. После approve два интервью выполняются параллельно,
показывают отдельные Transcript/источники/прогресс и дают общий Report, который
можно скачать и обсуждать через существующий Chat по точному Checkpoint pin.

Academy 3: Human-in-the-Loop. Academy 4: Parallelization, Subgraphs, Map-Reduce.
Предпосылки: этап 12, State, Send, Reducers, Checkpoints и Streaming.
Наличие кода не означает завершённую практику или понимание пользователя.

Ровно два аналитика, по два раунда. Нет генерации команды моделью, частичного
общего Report, автоматических retries, нового backend/frontend или CLI из HTTP.
Штатный бюджет: 5 model calls на Worker + 1 общий synthesis = 11 model calls,
4 поиска. Resume может повторить незавершённый внешний вызов, exactly-once нет.

## Файлы и разделение ответственности

Новый код команды расположен в `research_assistant/team/`, тесты — `tests/team/`.
Не добавлять учебные комментарии к каждому блоку исходников. Объяснения,
порядок чтения, функции/входы/выходы и фрагменты фактического кода — в README
пакета и итоговом руководстве. В ответах всегда указывать папку файла.

| Файл | Назначение |
| --- | --- |
| `research_assistant/team/__init__.py` | Публичный импорт фабрики Team Graph |
| `research_assistant/team/schemas.py` | Роли, решения Review, WorkerResult, Team State и Workflow |
| `research_assistant/team/graph.py` | Parent Nodes, interrupt, Send, Reducer и Fan-in |
| `research_assistant/team/worker.py` | Адаптация входов/выходов compiled Interview Core без записи Report |
| `research_assistant/team/sources.py` | Глобальный реестр, происхождение, явное преобразование ID |
| `research_assistant/team/providers.py` | Единственный общий synthesis по двум позициям |
| `research_assistant/team/progress.py` | Проекция parent/worker прогресса и восстановление UI |
| `research_assistant/team/materials.py` | Проверяемый адаптер завершённого Team Report для Chat |
| `research_assistant/team/demo.py` | Внутренние подмены и управляемая ошибка Worker B |
| `research_assistant/team/static/team.js` | Review ролей, отдельные панели интервью и общий статус |
| `research_assistant/team/static/team.css` | Расширение текущего дизайна, responsive/focus |
| `research_assistant/team/start-local.ps1` | Отдельный локальный запуск с явным режимом, портами и data-root |
| `research_assistant/team/README.md` | Архитектура, функции, команды и порядок чтения |

Общий Core выделяется в `research_assistant/interview/core.py` из существующей
реализации `research_assistant/interview/graph.py`. Нужные общие Nodes/конструкцию
графа выносить туда без второй копии логики. Standalone builder сохраняет
имена Nodes/поля State/Workflow и прежнюю топологию для Resume старых Threads;
его save_report остаётся самостоятельной обёрткой. Core допускает проверенную
роль/focus Team, но standalone по-прежнему назначает фиксированную роль этапа 12.

Точки интеграции: `research_assistant/server_graphs.py`, `langgraph.web.json`,
`research_assistant/web/service.py`, `research_assistant/web/app.py`,
`research_assistant/web/client.py`, существующие HTML/app.js и package-data
в `pyproject.toml`. Сохранять прежние изменения, API и поведение остальных режимов.

## Роли и Human-in-the-Loop

prepare_analysts без модели валидирует тему/уточнение и задаёт:

- analyst_id=A, название «Польза и возможности», focus на применениях,
  преимуществах и условиях получения пользы для введённой технической темы.
- analyst_id=B, название «Риски и ограничения», focus на ограничениях,
  отказах, компромиссах и условиях неприменимости для той же темы.

analyst_id фиксированы и уникальны; редактор не меняет ID/число аналитиков.
Названия — непустые строки до 120 символов, focus — непустые строки до 1000.
Тема/уточнение используют ограничения этапа 12. Лишние поля отклоняются.
Решения approve/edit/cancel валидируются Pydantic; edit передаёт ровно A/B.

review_analysts вызывает настоящий interrupt с ролями для формы. До Resume нет
вызовов model/search. approve использует подготовленные роли, edit сохраняет
проверенные поля пользователя, cancel завершает без интервью. Возобновление
review_analysts не перезапускает prepare_analysts и не затирает решение.

Роль и focus задают аналитическую перспективу в system instructions Analyst,
а не остаются неиспользуемыми полями. Валидация и обрамление инструкции сохраняют
общие правила источников/лимитов: текст роли/focus не получает полномочий отменять
их. Topic, clarification, Transcript и snippets остаются пользовательскими данными.

## Parent/Child Graph и State

```text
START → prepare_analysts → review_analysts
                              ├─ cancel → END
                              └─ approve/edit → Send(interview_worker, A)
                                               Send(interview_worker, B)
                                                        ↓
                                              collect_interviews
                                                        ↓
                                              generate_team_report
                                                        ↓
                                                   save_report → END
```

dispatch_interviews — маршрутизатор, возвращающий два настоящих Send.
Worker вызывает compiled Interview Core через поддерживаемую адаптацию
разных State schemas; вызов не заменять последовательным циклом.
Parent Run ограничивает max_concurrency=2. Каждый Worker получает отдельный
State с topic/clarification/analyst_id/role/focus и свои questions/answers/sources.

Core: prepare → ask → search → answer → Conditional Edge → summarize → результат.
Два раунда, второй вопрос использует свой Transcript. Synthesis сразу возвращает
ReportDraft/структурированные выводы; повторного model call для выводов нет.
Worker не пишет файл и не изменяет объект общего State. Возвращает только свой
WorkerResult: analyst_id, утверждённую роль/focus, Transcript, локальные Sources,
структурированные выводы, ограничения и завершённые исполнения шагов.

Результаты объединяет Reducer с ключом analyst_id: одинаковая повторная запись
того же результата не дублируется, конфликтующие результаты одного ID отклоняются.
collect_interviews проверяет ровно два результата A/B, соответствие утверждённым
ролям, полноту двух раундов и корректность ссылок. Затем упорядочивает A, B.
Один успех и одна ошибка не дают права формировать общий Report.

Team Workflow отдельно версионирован: mode=team, version=team-web-1.
State хранит роли/решение Review, результаты Workers, глобальный реестр и mapping,
происхождение источников, итоговый ReportDraft/Markdown/path, status/Workflow.
Внутренний State незавершённых интервью находится в Checkpoints Subgraphs;
публичное восстановление не должно зависеть только от итоговых WorkerResult.

## Persistence и Resume

Использовать native Checkpointer родителя и наследуемую persistence compiled
Subgraphs, без случайных новых Thread IDs и отдельных баз Workers. Сохранить
детерминированный порядок вызова Subgraph в worker adapter для устойчивых namespaces.

Pending Writes успешного A при ошибке B проверяются отдельным тестом с файловым
Checkpointer и новым Python-процессом. Проверить также Resume внутри B:
успешные вопросы/поиски и первый ответ B не повторяются, Transcript не дублируется,
A не запускается заново. Если фактическое API установленной версии требует
иного оформления wrapper/subgraph persistence, выбрать поддерживаемый вариант
по результату этого теста и отразить решение в implementation ledger.

При ошибке общего save_report Resume повторяет только сохранение; не интервью
и не synthesis. Финальный путь содержит Team artifact identity и отличается
от обычного Research и standalone Interview. Запись — существующим атомарным API.

## Источники и общий синтез

У каждого интервью остаются собственные S1/S2/... и исходный Transcript.
Fan-in проходит результаты в порядке A/B и строит общий реестр по точному URL.
Внешний порядок завершения не влияет на глобальные ID.

Хранить mapping вида A/S1 → S1, B/S1 → S2 и provenance с analyst_id/local_source_id
для каждого глобального источника. Повторный URL объединяет происхождение,
но не теряет локальную связь. Списки source_ids в структурированных выводах
преобразуются через mapping; текст ответов не переписывается string replace.
Локальные ссылки отдельных панелей берутся из их реестров, глобальные — из общего.

generate_team_report одним вызовом получает обе роли, структурированные выводы,
ограничения и материалы с глобальными ID. Инструкция требует представить обе
позиции, различия и неопределённость без выдуманного согласия или заявления,
что это независимые люди-эксперты. Ответ — ReportDraft с проверенными source_ids;
URL и Markdown-ссылки строятся существующим render_report из реестра.

## События, UI и восстановление

Расширить lifecycle этапа 12 полем analyst_id. Публичные события: parent run_id,
analyst_id (A/B, для Parent — отдельное обозначение parent), node, round,
execution_id, status, безопасная label, timestamp. События проходят allowlist;
namespace не должен терять принадлежность Worker. Запуск/ошибка/успех — реальные,
done не означает, что custom event сам записал Checkpoint. Token streaming
не обязателен и не имитируется нарезкой текста.

UI использует текущие типографику, цвета, отступы и компоненты. Режимы:
«Обычное» / «Одно интервью» / «Команда аналитиков». Форма topic/clarification;
Review — обычные поля названия/focus A/B, approve/edit/cancel без JSON.
Лимит «2 аналитика × 2 раунда» виден до запуска.

Во время работы — отдельные панели A/B: роль, Node, раунд, статус, вопросы,
ответы, раскрываемые источники и полный Transcript. Общая область показывает
ожидание двух интервью или синтез; два активных Worker не сводятся к одному Node.
После завершения — общий Report/download/Chat и доступ к обоим интервью.
На узком экране панели идут последовательно; цвет сопровождается текстом,
предусмотрены keyboard/focus/aria-live, перенос длинных строк и ошибки/Resume.

После reload читать сохранённые роли, оба внутренних State/историю Subgraphs,
Pending Writes и статус Run, а не вызывать модель. Переподключение использует
существующий request journal, Run и execution_id; сообщения не дублируются.
Устаревшая ошибка не перекрывает успешную попытку Resume. Потеря SSE не оставляет
бесконечный running. События другого Thread/пользователя не подмешиваются.

## Интеграция и Live

Новый server Graph `team` и Thread kind=team. BFF сохраняет owner checks,
idempotency и multitask strategy reject. Team Review и Resume маршрутизируются
по типу Workflow, не маскируются под Research. Явный team_materials adapter
проверяет завершённый Team Workflow, обе позиции и общий реестр перед Chat.
Сохраняются source Thread/checkpoint pin, Memory, Assistants и Streaming Chat.

Работающие Live/Studio не останавливать. Для разработки — отдельные порты/data-root;
конкретные свободные значения проверить перед запуском. Demo/fakes — только
внутренние проверки. Пользователю передать отдельный актуальный Live с явной
подписью и проверенной регистрацией Graph, без перезапуска прежнего Live.
При запуске Live не выполнять платные model/search calls; их проверку запускает
пользователь. Tracing не включать. Секреты остаются в серверном окружении.

## Приёмка и документация

Автономные tests: до approve/cancel ноль внешних вызовов; edit доходит до Workers
и system instructions; параллельность через Barrier/Event, бюджет 11/4, изоляция
Transcript, строгий Fan-in, коллизии локальных ID, точное URL dedupe/provenance,
некорректные ссылки/роли, ошибка B/Resume в новом процессе, повтор save без новых
model calls, Team Chat pin и регрессии standalone/Research/Chat/Memory.

Отдельные настоящие Demo HTTP/browser tests: Review → два Subgraphs → Report →
Chat; одновременные состояния; reload/reconnect/idempotency; ошибка B при успешном
A и Resume. Проверить 1280/375px, длинные строки, keyboard/focus и overflow,
включая применимые открытые критерии этапа 12. Скриншот не равен browser E2E.
Недоступные проверки записать явно; завершение этапа без evidence не заявлять.

Актуальная документация Context7 уже получена по Send/Map-Reduce, Subgraph
Persistence/Pending Writes, Streaming/namespaces. Проверены установленные версии:
LangGraph 1.2.16, Agent Server 0.16.2, SDK 0.4.8, checkpoint-sqlite 3.1.2.
Документация не заменяет тест фактической поддержки persistence/HTTP API.

Обновить spec.md, корневой README, руководство Interview и руководство Team:
Graph, файлы/функции, бюджеты, ID mapping, ошибки/Resume, Demo/Live, точные команды,
ручную практику и реальные проверки/ограничения. При начале реализации статус
этапа 13 — «в работе»; завершение только по критериям и проверке результата.
Новые устанавливаемые зависимости не планируются. Учебные изображения в
репозиторий, commit/push и публичный Deployment запрещены.

Финальный ответ сразу включает девять пунктов пользовательского задания:
сценарий; файлы; функции/входы/выходы/фрагменты кода; зависимости и stdlib;
путь UI → Review → Send → Subgraphs → Reducer → Report → Chat; команды/проверки/
ограничения; термины HITL/Subgraph/Send/Fan-out/Reducer/Fan-in/Map-Reduce/Pending
Writes; порядок чтения/практику; отличия Team от одного интервью и дополнительные вызовы.
