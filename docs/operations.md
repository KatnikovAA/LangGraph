# Эксплуатация

## Локальный запуск

Установка и ключи — в [README](../README.md#запуск).
Основной запуск: `scripts/start-web.ps1 -Mode live`; остановка:
`scripts/stop-web.ps1 -Mode live`. Порты — 2025 и 8080.

Отдельный экземпляр с явными портами и каталогом данных:

```powershell
.\research_assistant\team\start-local.ps1 -Mode live -AgentPort 2029 -WebPort 8084 -DataRoot '.research_assistant/team/live'
```

Не используйте занятые порты и data root работающего экземпляра. Для остановки
отдельного экземпляра создайте agent.stop и bff.stop в его data root.
Не применяйте основной stop-script к чужому экземпляру.

## Данные и backup

Основной Web хранит данные в `.research_assistant/web/<mode>/`:

- runtime/.langgraph_api — Threads, Checkpoints, Assistants;
- memory.sqlite — Profile и Notes;
- application.sqlite — привязки запросов и Run IDs;
- reports/ — Markdown.

Для backup штатно остановите оба процесса и скопируйте весь data root.
CLI Checkpoints в `.research_assistant/checkpoints.sqlite` отдельны от серверных.
Runtime-логи нужны для диагностики и исключены из Git.

## CLI

```powershell
.\.venv-web\Scripts\python.exe -m research_assistant --help
.\.venv-web\Scripts\python.exe -m research_assistant --topic 'Архитектура LangGraph' --review --search --report
.\.venv-web\Scripts\python.exe -m research_assistant --resume THREAD_ID
.\.venv-web\Scripts\python.exe -m research_assistant --discuss RESEARCH_ID --question 'Какие ограничения у выводов?'
.\.venv-web\Scripts\python.exe -m research_assistant --chat CHAT_ID --question 'Сравни основные подходы' --stream
```

History, Inspection, Replay/Fork, checkpoint pin и память доступны через --help.
Подготовка альтернативы отделена от выполнения. Новый artifact_id сохраняет
прежний Report при появлении ветки исследования.

## Проверки

GitHub Actions автоматически проверяет push в main и Pull Request. Ручной запуск:
GitHub → Actions → CI → Run workflow. Конфигурация: `.github/workflows/ci.yml`.
Основной набор выполняется на Windows / Python 3.12 без provider Secrets.
Отдельные HTTP/restart/checkout сценарии по умолчанию пропущены.

Перед коммитом можно выполнить политику безопасности локально:
`python scripts/check_repository_security.py`. Скрипт читает Git index; новые
изменения должны быть добавлены через git add. Он не читает локальный .env,
не печатает значения и не является исчерпывающим сканером секретов.
Реальные ключи храните только в локальном .env или серверном окружении;
не добавляйте их в GitHub Secrets для этого Workflow — они не требуются.

```powershell
.\.venv-web\Scripts\python.exe -m unittest discover -s tests -v
.\.venv-web\Scripts\python.exe -m compileall -q research_assistant tests scripts
.\.venv-web\Scripts\python.exe -m pip check
```

Основной набор использует подмены провайдеров. Opt-in сценарии требуют Web extra.
Перед HTTP-проверками поднимите изолированную Demo на адресах, ожидаемых тестами;
не используйте работающий Live. Читайте предусловия соответствующего test-файла.

```powershell
$env:RA_HTTP_TESTS='1'
.\.venv-web\Scripts\python.exe -m unittest discover -s tests -p test_web_http.py -v
Remove-Item Env:RA_HTTP_TESTS

$env:RA_RESTART_TESTS='1'
.\.venv-web\Scripts\python.exe -m unittest discover -s tests -p test_web_restart.py -v
Remove-Item Env:RA_RESTART_TESTS

$env:RA_CHECKOUT_TESTS='1'
.\.venv-web\Scripts\python.exe -m unittest discover -s tests -p test_web_checkout.py -v
Remove-Item Env:RA_CHECKOUT_TESTS
```

## Studio и конфигурация

langgraph.web.json регистрирует Graph, Store и tracing-настройки. Studio можно
подключить к локальному Agent Server для просмотра State и Checkpoints.
langgraph.json — отдельная offline-конфигурация с синтетическими источниками.
Tracing выключен по умолчанию; секреты хранятся в серверном окружении.
