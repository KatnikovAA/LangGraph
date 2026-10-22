# Interview Workflow

Два раунда Analyst/Expert по теме и уточнению пользователя. Вопросы формируют
поисковые запросы, ответы опираются на сохранённые snippets, итоговый synthesis
объединяет Transcript в Report с проверенными ID источников.

## Graph

```text
prepare_interview → ask_question → search_sources → answer_question
                        ↑                                |
                        └──────── следующий раунд ───────┘
                                      |
                         summarize_interview → save_report
```

Обычный успешный запуск: два Analyst calls, два Expert calls, один synthesis
и два поиска. Отсутствие результатов отражается как ограничение.

## Модули

- schemas.py — State и структурированные ответы, нормализация входа.
- core.py — общий Interview Core; переиспользуется Workers команды.
- graph.py — самостоятельный Workflow с сохранением Report.
- providers.py — prompts и structured output Analyst/Expert/synthesis.
- sources.py — стабильные ID и объединение источников по точным URL.
- progress.py — события running/done/error и безопасная проекция State.
- materials.py — проверка завершённого результата перед Chat.
- static/ — Transcript, Progress и Resume в Web Interface.
- demo.py — детерминированные подмены для автономных проверок.

## Persistence

Resume продолжает pending Node; успешные результаты сохраняются.
Незавершённый внешний вызов может повториться. Chat использует точный
завершённый Checkpoint и не перезапускает исследование.

Выберите «Одно интервью» в Web Interface. Общий запуск и проверки:
[README](../../README.md), [эксплуатация](../../docs/operations.md).
