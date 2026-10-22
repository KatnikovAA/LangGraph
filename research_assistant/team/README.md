# Команда аналитиков

Две независимые роли исследуют одну тему в параллельных интервью. Пользователь
редактирует name/focus и утверждает роли до обращений к модели и поиску.
Общий Report строится после обоих результатов и сохраняет provenance источников.

```text
prepare → review_analysts → Send → interview_worker A ─┐
                               → interview_worker B ─┤
                                                    collect → synthesis → save
```

## Запуск

Выберите «Команда аналитиков» в основном Web Interface. Для отдельного экземпляра:

```powershell
.\research_assistant\team\start-local.ps1 -Mode live -AgentPort 2029 -WebPort 8084 -DataRoot '.research_assistant/team/live'
```

Требуются .venv-web и ключи провайдеров в серверном .env. Занятые порты и активный
data root отклоняются. Для остановки создайте agent.stop и bff.stop в data root.
Внутренние проверки поддерживают явный -Mode demo и -FailWorkerB.

## Модули

- schemas.py — роли, WorkerResult, TeamState и idempotent Reducer.
- graph.py — Review, Send, collect и общий synthesis.
- worker.py — изолированный вход и вызов Interview Core.
- ../interview/core.py — переиспользуемые Nodes вопросов, поиска и ответов.
- sources.py — общий реестр ID, mapping и provenance.
- providers.py — структурированный synthesis общего отчёта.
- progress.py — безопасные события и проекция вложенного State.
- materials.py — проверка результата для Chat.
- static/ — Review и отдельные панели аналитиков.

Результат доступен для скачивания и обсуждения с точной привязкой к Checkpoint.
[Архитектура](../../docs/architecture.md) · [Эксплуатация](../../docs/operations.md).
