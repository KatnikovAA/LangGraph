# Technical Research Assistant

Самостоятельное Python-приложение для подготовки заявок на исследование технических тем.
Сейчас реализован только этап 1: приём темы, проверка и подготовка заявки через LangGraph.
Модель, поиск и создание отчёта пока не реализованы. API-ключи, сервисы и Studio не требуются.

## Установка в Windows PowerShell

Требуется установленный Python 3.11 или новее (проверено на 3.12.14).

```powershell
Set-Location 'F:\AI Agent\LangGraph'
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Активация окружения не требуется. Зависимости и версия Python указаны в `pyproject.toml`.

## Запуск

```powershell
.\.venv\Scripts\python.exe -m research_assistant --topic '  Архитектура LangGraph  '
```

```json
{
  "topic": "  Архитектура LangGraph  ",
  "normalized_topic": "Архитектура LangGraph",
  "status": "ready"
}
```

`ready` означает готовность заявки к планированию. Исследование ещё не выполнено.
JSON выводится в stdout в UTF-8. Исходная строка сохраняется, все последовательности
пробельных символов, включая табуляцию и переносы строк, заменяются одним пробелом.

Пустая тема отклоняется (пробельный аргумент работает также в старом Windows PowerShell):

```powershell
.\.venv\Scripts\python.exe -m research_assistant --topic '   '
$LASTEXITCODE # 2
```

В stderr: `Ошибка: Тема исследования не должна быть пустой.` Без traceback.
В PowerShell 7.3+ можно также передать точно пустую строку: `--topic ''`.
Аргумент `--topic` обязателен.

## Использование из Python

```python
from research_assistant.graph import build_graph

graph = build_graph()
request = graph.invoke({"topic": "Архитектура LangGraph"})
```

Путь данных: `START → validate_topic → prepare_request → END`.
Первый узел проверяет тему и добавляет `normalized_topic`, второй добавляет `status`.
Оба возвращают частичные обновления и не изменяют входной словарь.
Входной `TopicInput` содержит только `topic`; в `RequestState` выходные поля отмечены
`NotRequired`. Пустая тема поднимает `EmptyTopicError`, подкласс `ValueError`;
CLI обрабатывает только эту ожидаемую ошибку.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Проверяются результат графа, сохранение исходного ввода, нормализация пробельных
символов, отсутствие мутаций состояния, отклонение пустой темы и поведение CLI.
