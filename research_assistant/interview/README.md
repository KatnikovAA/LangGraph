# Этап 12: код интервью в одной папке

Это отдельный режим существующего Research Assistant. Главная точка входа —
`build_interview_graph()` из `research_assistant/interview/graph.py`. Сервер и UI используют тот же пакет,
что автономные тесты. Этап 13 здесь не реализован.

## Порядок чтения

1. `schemas.py`: поля State, InterviewQuestion/InterviewAnswer, фиксированная роль.
2. `graph.py`: шесть Nodes и ограниченная Conditional Edge после ответа.
3. `demo.py`: подмены Analyst, Expert, synthesis и search; удобно начать без API.
4. `sources.py`: устойчивые S1/S2 и точное объединение URL.
5. `providers.py`: отдельные system prompts Analyst/Expert/synthesis, structured output.
6. `progress.py`: обёртка Node, реальные running/done/error и безопасная проекция.
7. `materials.py`: проверка завершённого Workflow перед существующим Chat.
8. `static/interview.js` и `static/interview.css`: Transcript, источники, схема и Resume.
9. `../../tests/interview/`: fake tests и настоящие HTTP-сценарии.

## Graph

```text
START → prepare_interview → ask_question → search_sources → answer_question
                                ↑                              │
                                └── один ответ ────────────────┤
                                                               │ два ответа
                                                               ↓
                                     summarize_interview → save_report → END
```

В штатном успешном выполнении: два Analyst calls, два Expert calls и один
synthesis call = 5 model calls; два поиска. prepare_interview не вызывает модель.
save_report переиспользует атомарный write_report и не вызывает report generator.

State сохраняет отдельные questions/answers, поисковые запросы, Transcript,
источники, round, ReportDraft/Markdown/path, Workflow/status, limitations и
завершённые исполнения Progress Events. Resume продолжает pending Node; успешные
раунды и поиски не повторяются. Незавершённый внешний вызов может повториться:
exactly-once не обещается, SDK retries модели отключены существующим create_model.

## Входы и выходы

| Функция | Получает | Возвращает / эффект |
| --- | --- | --- |
| validate_interview_input | topic, clarification | Нормализованные строки и фиксированная роль |
| build_interview_graph | Опциональные Analyst/Expert/synthesis/search, Checkpointer, output_dir | Compiled StateGraph |
| ask_analyst | Тема, уточнение, роль, прежний Transcript | InterviewQuestion: text/search_query |
| answer_expert | Вопрос, реестр, доступные ID текущего поиска | InterviewAnswer: text/source_ids |
| summarize_transcript | Тема, Transcript, реестр | Единственный итоговый ReportDraft |
| merge_sources | Старый реестр, результаты поиска, раунд | Новый реестр и доступные ID; старый реестр не мутирует |
| validate_source_ids | ID из модели, разрешённые ID | Уникальные проверенные ID либо ошибка |
| tracked | Имя Node и его функция | Node с настоящими lifecycle событиями и сохранённой длительностью |
| project_progress | custom payload, авторитетный Run ID | Только безопасные публичные поля либо None |
| interview_materials | Завершённый State и ID исходного Thread | Материалы существующего Chat после проверки Workflow |
| InterviewUI.render | Public State projection, статус Run | Transcript/источники/Nodes/Resume в DOM |

Analyst и Expert — роли отдельных вызовов модели, не постоянно работающие
процессы. Interview Loop — возврат после первого ответа. Conditional Edge
`after_answer` выбирает возврат или синтез. Transcript хранит вопрос, ответ,
раунд и связанные ID. Progress Events показывают только этап работы,
без hidden reasoning. Пример фактического кода:

```python
def after_answer(state):
    return 'ask_question' if len(state['answers']) < 2 else 'summarize_interview'
```

Второй вопрос получает `state['transcript']`; точный повтор первого вопроса
отклоняется без автоматического дополнительного вызова. Семантическое качество
Live-вопроса обеспечивается инструкцией модели и требует отдельной Live-проверки.

## Подключения вне этой папки

- `server_graphs.py` / `langgraph.web.json`: фабрика и регистрация `interview`.
- `web/service.py`: create_interview, Resume, idempotency, owner checks, Chat pin.
- `web/app.py`: API allowlist, public State, active Run, SSE, static mount.
- `web/client.py`: пропускает только проверенные custom Progress Events.
- `web/static/index.html` / `app.js`: текущая форма, выбор режима, подключение UI,
  lifecycle SSE, восстановление, существующие Report/download/discuss.
- `chat.py`: отдельное разрешение пустого source registry только для
  server-validated Interview materials; обычный Research сохраняет прежнее правило.
- `pyproject.toml`: упаковка JS/CSS/README/launcher; новых зависимостей нет.

## Demo

```powershell
.\research_assistant\interview\start-demo.ps1
# http://127.0.0.1:8082 ; Agent http://127.0.0.1:2027
```

Launcher проверяет свободные порты, использует отдельный data-root
`.research_assistant/interview-demo`, запрещает существующий web data-root и
повторное использование папки с ещё работающими процессами. Запускает текущие
entrypoints web.agent/web, без нового backend. /ready должен вернуть mode=demo.
Уже занятые порты: выберите -AgentPort и -WebPort; работающие серверы не останавливайте.

```powershell
.\research_assistant\interview\start-demo.ps1 -AgentPort 2028 -WebPort 8083 `
  -DataRoot '.research_assistant/interview-error-demo' -FailSecondAnswerOnce -DelaySeconds 2
```

Fault injection только через окружение Demo, не через HTTP/Live. Один сбой
второго Expert на весь указанный data-root; marker сохраняется после рестарта.
После ошибки нажмите Resume. Для повторного упражнения используйте новую папку.
Остановить именно эти серверы: создать agent.stop и bff.stop внутри их data-root.

Источники и тексты Demo явно обозначены. Live фабрика использует существующие
Polza/Tavily; платные запросы и provider quality в этом этапе не проверялись.
Interview использует custom/updates: token streaming вопросов/ответов пока
не включён. Готовый текст не нарезается для имитации provider streaming.

## Путь данных и зависимости

Форма → BFF create_interview → SDK Run(interview) → Nodes → custom events →
безопасная SSE projection → InterviewUI; Checkpoints → State projection после
reload; synthesis → render_report → atomic write_report → download →
interview_materials → существующий Chat с точным checkpoint pin → Memory/Assistants.

Новые пакеты: нет. Уже установленные: LangGraph (Graph/Checkpointer/stream writer),
Pydantic (схемы), langchain-openai/langchain-core/OpenAI (existing create_model,
structured invoke и ошибки), Tavily/requests (existing search_web),
SDK/Starlette/httpx (существующие Run/SSE/API), checkpoint-sqlite (persistence tests).
Стандартная библиотека нового runtime: json, copy, datetime, uuid, os, time,
pathlib, typing; unittest/tempfile/threading/concurrent.futures — в тестах.

Подробная приёмка и ограничения: `../../docs/interview-walkthrough.md`.
