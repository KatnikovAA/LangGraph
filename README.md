# Technical Research Assistant

Python-приложение принимает техническую тему и составляет структурированный план
исследования на русском языке через LangGraph и Польза AI.
По желанию план можно проверить, исправить и утвердить в терминале.
После утверждения плана можно найти источники через Tavily.
В полном режиме приложение формирует короткий Markdown-отчёт и сохраняет Thread
в SQLite, чтобы продолжить его после перезапуска процесса.

Компактный вывод: модель получает инструкцию составить 1 раздел с 1 вопросом
и до 40 слов во всём плане. Это пожелание промпта, не жёсткий лимит схемы.
Tavily запрашивается с `max_results=1` на раздел; каждый сохраняемый `snippet`
содержит не более 500 символов (обрезается локально после проверки ответа).
Полный ответ API всё ещё может быть длиннее. Ручной план с несколькими разделами
по-прежнему вызывает отдельный запрос для каждого раздела.
В режиме `--report` snippets передаются модели; сокращение уменьшает входной
контекст Report. В прежних режимах дополнительного LLM-вызова нет.

## Установка в Windows PowerShell

Требуется Python 3.11 или новее (фактически проверяется Python 3.12).

```powershell
Set-Location 'F:\AI Agent\LangGraph'
# Только если окружения ещё нет:
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Активация окружения не требуется.

## Настройки Польза AI

Если `.env` ещё нет, создайте его из примера:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Заполните локальный `.env`:

```dotenv
POLZA_API_KEY=
POLZA_MODEL=
POLZA_BASE_URL=https://polza.ai/api/v1/
```

- `POLZA_API_KEY` — секретный ключ Польза AI.
- `POLZA_MODEL` — точный ID выбранной вами модели из каталога с префиксом
  провайдера. Требуется поддержка `response_format: json_schema`.
  Платная модель по умолчанию не выбирается.
- `POLZA_BASE_URL` — необязательный адрес API, по умолчанию адрес выше.

`.env` читается из текущей рабочей папки при обращении к модели.
Переменные окружения имеют приоритет. Файл исключён из Git.
Не отправляйте ключ в чат и не сохраняйте его в `.env.example`.

Используется `ChatOpenAI.with_structured_output` с `method="json_schema"`,
`strict=False` и локальной проверкой Pydantic. Поддержка схемы зависит от модели:
отказ API или несовместимый ответ завершает запуск ошибкой без фиктивного плана.
[Интеграция LangChain](https://polza.ai/docs/integracii/langchain),
[структурированный вывод](https://polza.ai/docs/gaidy/structured-output).

## Запуск

Команда обращается к выбранной модели и может расходовать баланс Польза AI:

```powershell
.\.venv\Scripts\python.exe -m research_assistant --topic '  Архитектура LangGraph  '
```

Пример структуры результата (иллюстрация, не результат реального запроса):

```json
{
  "topic": "  Архитектура LangGraph  ",
  "normalized_topic": "Архитектура LangGraph",
  "status": "planned",
  "plan": {
    "title": "Исследование архитектуры LangGraph",
    "sections": [
      {
        "title": "Граф и состояние",
        "questions": ["Как узлы обновляют состояние?"]
      }
    ]
  }
}
```

В промпте запрошены 1 раздел с 1 вопросом и до 40 слов во всём плане.
Количество разделов, вопросов и слов программно не ограничивается;
лимит выходных токенов приложение не задаёт. Модель может отступить от пожеланий
промпта. Структура JSON проверяется. Строки обрезаются по краям
и проверяются на непустоту. Русский язык, соответствие теме и отсутствие повторов
задаются инструкцией модели; семантическое качество не гарантируется схемой.
`planned` означает наличие плана, исследование ещё не выполнено.

JSON выводится в stdout в UTF-8, исходная строка сохраняется.
Пробелы, табуляция и переносы строк нормализуются в `normalized_topic`.
Пустая тема отклоняется до конфигурации и вызова API:

```powershell
.\.venv\Scripts\python.exe -m research_assistant --topic '   '
$LASTEXITCODE # 2
```

В stderr: `Ошибка: Тема исследования не должна быть пустой.`
Ожидаемые ошибки конфигурации, подключения и структуры также дают stderr и код 2
без traceback и успешного JSON. Повторных запросов нет; таймаут API — 60 с.

## Использование из Python

```python
from research_assistant.graph import build_graph

graph = build_graph()
result = graph.invoke({"topic": "Архитектура LangGraph"})
```

Путь: `START → validate_topic → prepare_request → generate_plan → END`.
Первый узел добавляет `normalized_topic`, второй — промежуточный `status="ready"`.
Третий передаёт нормализованную тему генератору, проверяет `ResearchPlan`, добавляет
сериализованный `plan` и `status="planned"` только после успеха.
Все узлы возвращают частичные обновления без изменения входного словаря.
Выходные поля `RequestState` помечены `NotRequired`; вход содержит только `topic`.
Для тестов `build_graph(plan_generator)` принимает функцию от темы,
возвращающую `ResearchPlan` или словарь плана.

## Проверка и утверждение плана

Прежний режим возвращает `status="planned"`:

```powershell
.\.venv\Scripts\python.exe -m research_assistant --topic 'Память AI-агентов'
```

Интерактивный режим:

```powershell
.\.venv\Scripts\python.exe -m research_assistant --topic 'Память AI-агентов' --review
```

После генерации граф приостанавливается в `review_plan` через `interrupt()`.
CLI показывает план и меню: `1` — утвердить, `2` — загрузить исправленный план,
`3` — отменить. При выборе `2` введите путь к UTF-8 JSON-файлу (BOM допустим).
Файл содержит только объект плана, без topic/status и внешнего поля plan:

```json
{
  "title": "Память AI-агентов",
  "sections": [
    {
      "title": "Состояние графа",
      "questions": ["Как сохраняется состояние?", "Как изолировать исследования?"]
    }
  ]
}
```

Проверенный исправленный план показывается повторно. Введите `да`, чтобы
утвердить его, либо `нет`, чтобы вернуться к меню. Ошибка команды, пути,
кодировки, JSON или схемы позволяет повторить ввод. EOF и Ctrl+C во время
ожидания решения означают отмену. Без интерактивного stdin режим `--review`
завершается с кодом 2 до вызова модели; stdout можно перенаправить в файл.

При утверждении CLI продолжает граф через `Command(resume=...)`:
`approved` означает утверждённый план, `cancelled` — отмену пользователем.
Оба результата возвращаются как итоговый JSON с кодом 0. Отмена сохраняет
исходный план. Отказ от подтверждения правки не меняет его. Исходные `topic`
и `normalized_topic` сохраняются. Исследование ещё не выполняется.
Предварительный план, меню и ошибки ввода идут в stderr, только итоговый JSON —
в stdout. Вызов модели при продолжении не повторяется.

Для ручной проверки запустите review-режим и выберите `1`; в следующем запуске
выберите `3`; затем проверьте `2` с ошибочным путём и исправленным файлом.
Каждый новый запуск с непустой темой вызывает настроенную модель и может быть платным.

### Пауза и продолжение из Python

```python
from uuid import uuid4
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from research_assistant.graph import build_graph

checkpointer = InMemorySaver()
graph = build_graph(review=True, checkpointer=checkpointer)
config = {"configurable": {"thread_id": uuid4().hex}}
paused = graph.invoke({"topic": "Память AI-агентов"}, config)
plan = paused["__interrupt__"][0].value["plan"]
# Здесь вызывающий код получает решение человека.
result = graph.invoke(Command(resume={"action": "approve"}), config)
```

Другие решения: `{"action": "cancel"}` или
`{"action": "edit", "plan": corrected_plan}`. Узел самостоятельно проверяет
решение и исправленный план; неверное решение вызывает `ValidationError`.
Не используйте `Command(update=...)` для передачи пользовательской правки.
Для нового исследования создавайте новый `thread_id`; для resume сохраняйте
тот же граф, checkpointer и config. `build_graph` требует явный checkpointer
при `review=True`; прежний `build_graph(plan_generator)` работает как раньше.

Путь: `START → validate_topic → prepare_request → generate_plan → review_plan → END`.
Во время паузы статус остаётся `planned`. При resume узел `review_plan`
запускается с начала; вызов API находится в предыдущем узле `generate_plan`.
`interrupt()` не обёрнут в перехват исключений и передаёт сериализуемый payload.
`InMemorySaver` хранит данные только в текущем процессе: после его завершения
пауза теряется. Восстановление после перезапуска пока не поддерживается.

## Поиск по утверждённому плану

Обновите зависимости (включая официальный `tavily-python`):

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
notepad .env
```

Добавьте в существующий `.env` строку `TAVILY_API_KEY=ваш_ключ`.
Файл исключён из Git; ключ не нужен для прежних режимов и отмены до поиска.
Не заменяйте настройки Польза AI. Значения окружения имеют приоритет над `.env`.

Три режима PowerShell:

```powershell
# Только план: planned
.\.venv\Scripts\python.exe -m research_assistant --topic 'Память AI-агентов'

# Проверка человеком без поиска: approved / cancelled
.\.venv\Scripts\python.exe -m research_assistant --topic 'Память AI-агентов' --review

# Проверка человеком, затем поиск: sources_found / no_sources / cancelled
.\.venv\Scripts\python.exe -m research_assistant --topic 'Память AI-агентов' --review --search
```

`--search` без `--review` отклоняется с кодом 2 до обращения к API.
В поисковом режиме `1` в меню утверждает текущий план и запускает поиск;
`2` позволяет сначала загрузить и подтвердить правку; `3` завершает с cancelled
без поиска. Генерация плана при продолжении не повторяется.

Путь после `review_plan` выбирает runtime Router через `add_conditional_edges`:

```text
START → validate_topic → prepare_request → generate_plan → review_plan
                                                           ├─ approved → prepare_search → Workers → collect_sources → END
                                                           └─ cancelled → END
```

`if search` при построении выбирает состав графа. Conditional Edge во время
выполнения выбирает путь по текущему status после решения человека. В режиме
поиска безусловного ребра review_plan → END нет. При `--review` без `--search`
сохраняется прежнее завершение после review_plan.

Для каждого раздела окончательного плана формируется один запрос:
`normalized_topic + title раздела + все questions`, соединённые пробелами.
Запросы выполняются отдельными LangGraph Tasks с max_concurrency=2, без нового LLM-вызова. Tavily вызывается
с `search_depth="basic"`, `max_results=1`, `include_answer=False`,
`include_raw_content=False`, `auto_parameters=False`, таймаутом 30 секунд.
Автоматических повторов нет; объём поиска равен числу утверждённых разделов.

У Tavily [максимум 400 символов в запросе](https://help.tavily.com/articles/5504684071-optimizing-your-query-parameter).
Все строки проверяются до первого поискового запроса. Превышение даёт понятную
ошибку с кодом 2; запрос не обрезается. При необходимости сократите тему или
текст раздела в исправленном плане перед утверждением. Размер самого плана,
количество разделов, вопросов и выходных токенов технически не ограничиваются.

В итоговый JSON добавляется список `sources`. Пример одного элемента:

```json
{
  "title": "Документация",
  "url": "https://example.org/docs",
  "snippet": "Фрагмент результата поиска",
  "section_indexes": [0, 2]
}
```

Индексы разделов начинаются с 0. Точные дубли URL объединяются в порядке
первого появления; title и snippet сохраняются от первого результата,
section_indexes объединяются без повторов. Пробелы по краям title и url удаляются,
остальные различия URL сохраняются (например, наличие завершающего `/`).

Каждый источник проверяется `Source`: непустой title, HTTP(S) URL, строковый
snippet. Поле `content` Tavily становится snippet; если content отсутствует,
snippet пустой. `content=null`, неверный URL, пустой title, неверный JSON или
отсутствующий список results считаются ошибкой всего поиска. Некорректные
элементы не пропускаются молча; ссылки и фрагменты не придумываются.

- `sources_found`: все запросы успешны, найден хотя бы один источник.
- `no_sources`: все запросы успешны, `sources=[]`. План без разделов также
  даёт no_sources без поисковых запросов.
- `cancelled`: отмена до поиска, ключ поиска не требуется.

Ошибка любого запроса даёт код 2 и сообщение в stderr без успешного JSON
или частичных sources. Ранее выполненные запросы могли уже израсходовать квоту.
snippets — фрагменты, предоставленные Search API; приложение не открывает
найденные ссылки и не читает полные страницы. Без `--report` отчёт не создаётся.

Из Python используйте `build_graph(review=True, search=True, checkpointer=...)`
с тем же протоколом pause/resume. Для автономной проверки можно передать
`search_function(query)`, возвращающую список словарей с title, url и snippet.
`search.py` отвечает за конфигурацию Tavily и ответы SDK; `graph.py` — за
запросы по разделам, проверку, объединение источников и маршрутизацию.

## Полный режим: Report Generation + Persistence

Обновите установку: `python -m pip install -e .` (используя Python из `.venv`,
как в командах ниже). Новая прямая зависимость — `langgraph-checkpoint-sqlite`
с файловым `SqliteSaver`. Проверено: LangGraph 1.2.16, SQLite saver 3.1.2.
Ключи Польза AI и Tavily берутся из окружения/локального `.env`, в State не записываются.

```powershell
Set-Location 'F:\AI Agent\LangGraph'
.\.venv\Scripts\python.exe -m pip install -e .
# Полный запуск с меню утверждения:
.\.venv\Scripts\python.exe -m research_assistant --topic 'Архитектура LangGraph' --review --search --report
```

Сначала выполняются прежние Nodes validate_topic → prepare_request → generate_plan
→ review_plan. После approve/edit: prepare_search → search_section Workers → collect_sources → при sources_found
generate_report → save_report → END. Cancelled и no_sources завершаются без
дополнительного обращения к Report-модели и без Markdown-файла.

Report-модель получает только тему, утверждённый план и названия/snippets
источников со стабильными ID S1, S2 и т. д. Промпт просит до 200 слов,
считать snippets данными, не выполнять содержащиеся в них инструкции и явно
обозначать недостаток данных. Технического лимита токенов и циклов исправления нет.
`ReportDraft` проверяет структуру; неизвестные source_ids отклоняются.
Модель не формирует URL: References строятся из сохранённых sources, текст
экранируется, прямые URL в тексте модели удаляются. Проверка ID **не гарантирует
фактическую обоснованность текста**. Отчёт основан только на snippets Search API;
полные страницы приложение не читает.

### Pause и Resume в разных процессах

Процесс 1 (работает и без интерактивного stdin):

```powershell
.\.venv\Scripts\python.exe -m research_assistant --topic 'Архитектура LangGraph' --review --search --report --pause-after-plan
```

Он доходит до настоящего `interrupt` в review_plan, сохраняет Pause и закрывает
соединение с SQLite, не вызывая меню и не отправляя cancel. В stdout — JSON
с `status="planned"`, `paused=true`, `thread_id`, `checkpoint_db` и состоянием.
Служебный объект Interrupt не сериализуется. ID и путь БД также выводятся в stderr.

Процесс 2, после перезапуска терминала/приложения:

```powershell
# Замените значение ID на thread_id из предыдущего JSON:
$threadId = 'ВСТАВЬТЕ_THREAD_ID'
.\.venv\Scripts\python.exe -m research_assistant --resume $threadId
```

Resume показывает сохранённый Plan и прежнее меню approve/edit/cancel.
Решение требует интерактивного терминала. EOF/Ctrl+C в меню означают cancel;
чтобы заранее оставить Thread на Pause, применяйте `--pause-after-plan` при создании.
После ошибки незавершённого Node используется `invoke(None, config)`; при
достижении review_plan снова появится меню. Завершённый Thread возвращает
сохранённое состояние без генерации, поиска и перезаписи Markdown.

Можно задать пути при создании:

```powershell
$customPause = .\.venv\Scripts\python.exe -m research_assistant --topic 'Архитектура LangGraph' --review --search --report --pause-after-plan --checkpoint-db '.research_assistant\custom.sqlite' --output-dir 'reports\custom' | ConvertFrom-Json
.\.venv\Scripts\python.exe -m research_assistant --resume $customPause.thread_id --checkpoint-db '.research_assistant\custom.sqlite'
```

При Resume разрешён только `--checkpoint-db` в дополнение к ID. Тему, режим,
output-dir и Pause менять нельзя. Неизвестные Threads и несовместимые версии,
режимы или пути отклоняются до внешних запросов. Путь БД по умолчанию вычисляется
от рабочей папки; из другой папки укажите прежний абсолютный `--checkpoint-db`.
Output-dir берётся из сохранённого State, где пути уже абсолютные.

### Файлы, статусы и границы восстановления

- `.research_assistant/checkpoints.sqlite` — дефолтная БД Checkpoints: вход,
  Plan, sources, Markdown, статус и положение Workflow. Сохранение `durability="sync"`
  завершается перед следующим шагом. Версия Workflow и параметры режима сохраняются
  вместе со State. SQLite-соединение живёт в контекстном менеджере на весь запуск.
- `reports/report-<sha256 thread_id>.md` — результат для чтения. Имя безопасно и
  детерминировано; тема не используется как путь. Временный файл создаётся рядом,
  затем `os.replace` атомарно заменяет итоговый файл. Повторная запись не создаёт
  дубликатов. UTF-8 сохраняет кириллицу.
- `report_ready` — Markdown уже получен, запись ещё не подтверждена;
  `completed` — файл успешно записан. `planned`, `cancelled`, `sources_found` и
  `no_sources` сохраняют прежний смысл. `paused` в JSON описывает Pause, не статус.

Markdown-файл не заменяет Checkpoint: для восстановления нужны БД и прежний
thread_id. Если после завершения удалить Markdown вручную, Resume вернёт сохранённый
путь и не восстановит файл автоматически. БД, reports и временные файлы исключены
из Git; пользовательские каталоги вне дефолтных путей исключайте самостоятельно.

**Resume может расходовать баланс.** Сохранённые завершённые Nodes не повторяются,
но Node, остановленный до фиксации результата, может выполниться заново. Exactly-once
внешних запросов не гарантируется. Каждый search_section выполняет один запрос:
при сбое failed Task может повторить его. Успешные Tasks с сохранёнными Pending Writes
при Resume не повторяются. При ошибке записи
после сохранения report_ready Resume использует сохранённый report_markdown и повторяет
только save_report. Настройки модели при повторном API-вызове читаются из текущего `.env`.

### Порядок чтения кода

`schemas.py` (ReportDraft/ReportSection) → `reporting.py` (модель, Markdown,
атомарная запись) → `graph.py` (Nodes и Router) → `persistence.py` (SqliteSaver,
параметры и совместимость Thread) → `cli.py` (флаги, меню, запуск и Resume).
Общая `planning.create_model()` задаёт одинаковые настройки модели Plan и Report.
В тестах генераторы Plan, Search и Report заменяются независимо.

## Parallelization, Reducers и Map-Reduce

Поиск разделён на подготовку заданий, динамический Fan-out и общий Fan-in:

```text
review_plan
  cancelled → END
  approved → prepare_search
               ├─ Send(search_section, job 0) ─┐
               ├─ Send(search_section, job 1) ─┤
               └─ Send(search_section, job N) ─┴→ collect_sources
                                                   ├─ no_sources → END
                                                   └─ sources_found → Report / END
```

Пустой Plan идёт из prepare_search прямо в collect_sources. Все строки запросов
проверяются **до** первого Search API. Worker Input (`SearchWorkerInput`) содержит
только section_index и query; `Send` создаёт Task зарегистрированного search_section
со своим входом. Модель для распределения заданий не вызывается.

Worker делает один вызов поиска, проверяет результат и возвращает только одну
batch в search_batches. Ни status, ни окончательные sources он не меняет.
Общий `SearchState` расширяет прежний RequestState только в поисковых режимах:

```python
search_batches: Annotated[list[SearchBatch], operator.add]
```

Без Reducer несколько Workers записывали бы один обычный State key в одном
super-step, что LangGraph отклоняет как конфликт параллельных обновлений.
`operator.add` конкатенирует списки batches. Возврат `[]` не очищает такой список;
один Thread проходит один поисковый этап, повторный цикл здесь не реализован.

Fan-in — ребро `search_section → collect_sources`: сбор начинается после окончания
всего Worker super-step. collect_sources проверяет по одной batch на раздел,
сортирует по section_index, сохраняет порядок внутри batches и объединяет точные
URL. Название/snippet берутся из первого результата в порядке разделов, независимо
от порядка завершения Tasks. Report запускается один раз после полного сбора.

Лимит задаётся верхним полем RunnableConfig: `{"max_concurrency": 2,
"configurable": {"thread_id": "..."}}`. Он установлен в CLI для начала и Resume,
а также как default config собранного Graph. В Python его можно переопределить
в config. Общего изменяемого клиента Tavily нет: search_web создаёт собственные
Session и клиент на каждый вызов. Подменный search_function должен быть пригоден
для одновременных вызовов. План по умолчанию всё ещё содержит один раздел:
это один Worker; несколько Workers появляются при утверждении нескольких разделов.

### Ошибка ветки и совместимость Checkpoints

Ошибка Worker остаётся ошибкой CLI (stderr, код 2, без успешного JSON и Report).
Автоматический RetryPolicy не добавлен. Успешные Task results сохраняются как
Pending Writes; при явном `--resume` через новый saver/Graph они используются
повторно, а failed Task запускается заново. Fan-in не получает двойные batches.
API-вызов failed Task может расходовать баланс повторно; exactly-once нет.

**WORKFLOW_VERSION теперь 2.** Структура Nodes/State изменилась. Threads версии 1,
включая сохранённые ранее Pause, отклоняются до любых API-вызовов; автоматической
миграции нет. Старая БД и файлы не удаляются. Для нового Workflow создайте новый
Thread обычной командой с `--topic`; версия 2 может использовать тот же SQLite-файл.

Порядок чтения поиска: `SearchWorkerInput`/`SearchBatch`/`SearchState` →
`prepare_search` → `dispatch_search` → `search_section` → `collect_sources` →
`build_graph` в graph.py, затем config в cli.py и совместимость в persistence.py.
Новых устанавливаемых зависимостей нет: Send — из LangGraph, Annotated — из typing,
operator.add — из стандартной библиотеки Python.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Тесты работают без сети, реальных ключей и оплаты. Генератор подменяется,
а API-адаптер проверяется через локальный HTTP-транспорт с заданными ответами.
Это не подтверждает работу реального подключения.
Проверяются нормализация, сохранение исходной темы, ограничения схемы, CLI,
ошибки конфигурации, API и структуры. Реальный вызов выполняется отдельно
после настройки и разрешения пользователя.
Также проверяются pause/resume, утверждение и отмена, замена плана, повторный
ввод после ошибок, EOF/Ctrl+C, отсутствие повторной генерации, изоляция thread_id,
отсутствие мутаций входного состояния и чистый JSON в stdout.
Поиск проверяется подменной функцией и настоящим TavilyClient с локальным
HTTP-адаптером: параметры и таймаут, маршруты approve/edit/cancel, запрос на
каждый раздел, дедупликация, пустая выдача, ошибочные ответы, HTTP-ошибки,
отсутствие ключа и лимит длины. Реального подключения к Tavily эти тесты
не подтверждают. Модель и поиск вызываются реально только по отдельному разрешению.

Report/Persistence проверяются во временных каталогах с настоящим SQLite-файлом:
References, неизвестные ID, UTF-8, атомарная замена, отсутствие дублей, ошибки
генерации/записи, Resume после ошибки и завершения, изоляция Threads, отсутствие
ключей в Checkpoints. `persistence_worker.py` запускается тестом в отдельных
subprocess: Pause → новый процесс Resume → ещё один процесс завершённого Resume.
Plan во втором процессе запрещён тестом; все сервисы подменены. HTTP-запрос Report
проверяется настоящим ChatOpenAI через локальный MockTransport, без сети и оплаты.

`test_parallel_search.py` дополнительно проверяет реальное перекрытие Workers
через Event с ограниченными ожиданиями, лимит 2, разный порядок завершения,
Fan-in/Report один раз, полноту batches и Worker partial updates без мутаций.
После сбоя ветки закрывается SQLite-соединение и создаётся новый saver/Graph:
успешная Task не повторяется, failed повторяется, дубликатов нет. Старые Threads
версии 1 проверяются на отказ CLI без API и удаления базы. Проверки многосекционных
планов используют искусственный Plan, а не меняют компактный System Prompt.
