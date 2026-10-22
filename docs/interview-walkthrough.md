# Этап 12 — запуск, приёмка и ограничения

## Что доступно

В существующем Web Interface: режим «С интервью», тема/уточнение, фиксированный
аналитик, два раунда, источники с title/URL/snippet, схема Nodes, реальные
running/done/error, Resume, Markdown download и существующий Chat по результату.
Текущие дизайн, Research/Review, Memory и Assistants сохранены.

Код и учебный порядок: `research_assistant/interview/README.md`.
План: `docs/superpowers/plans/2026-10-22-interview.md`.
Журнал evidence: `docs/superpowers/plans/stage12-progress.md`.

## Ручной сценарий

1. Откройте /ready и проверьте mode=demo; UI находится по корню того же адреса.
2. «Новое исследование» → «С интервью». Введите техническую тему и уточнение.
3. Запустите. Видны роль «Технический аналитик» и лимит «2 раунда».
4. В «Ход выполнения» наблюдайте active Node и round. Первый вопрос появляется
   до завершения ответа; второй уточняет материал первого ответа.
5. Перезагрузите экран во время работы: тот же Thread продолжает Run,
   исходный create_interview POST не отправляется заново.
6. Раскройте S1: title, настоящий сохранённый URL и snippet видны отдельно.
7. В fault-once Demo второй ответ останавливается: первый раунд сохранён,
   pending шаг отмечен ошибкой, синтез ещё ожидает. Нажмите Resume.
8. После completed скачайте Markdown и нажмите «Обсудить этот результат».
   Chat показывает checkpoint pin; задайте вопрос и при желании используйте Memory.
9. Выберите сохранённое интервью, reload, сравните Transcript и Checkpoint
   в диагностике. Переключите пользователя: чужие Threads не появляются.

## Команды

```powershell
Set-Location 'F:\AI Agent\LangGraph'
.\research_assistant\interview\start-demo.ps1
# defaults: Agent 2027 / Web 8082 / .research_assistant/interview-demo
.\.venv-web\Scripts\python.exe -m unittest discover -s tests/interview -v

$env:RA_TEST_BASE_URL='http://127.0.0.1:8082'
$env:RA_INTERVIEW_HTTP_TESTS='1'
.\.venv-web\Scripts\python.exe -m unittest discover -s tests/interview -p test_http.py -v
Remove-Item Env:RA_INTERVIEW_HTTP_TESTS

$env:RA_HTTP_TESTS='1'
.\.venv-web\Scripts\python.exe -m unittest discover -s tests -p test_web_http.py -v
Remove-Item Env:RA_HTTP_TESTS
.\.venv-web\Scripts\python.exe -m unittest discover -s tests -q
.\.venv-web\Scripts\python.exe -m compileall -q research_assistant tests
.\.venv-web\Scripts\python.exe -m pip check
git diff --check
```

Не запускайте HTTP tests на Live. Для ошибки второго ответа используйте
launcher -FailSecondAnswerOnce с новым отдельным DataRoot. DelaySeconds
помогает наблюдать настоящий незавершённый вызов Demo, не имитируя токены.

## Evidence 2026-10-22

- Baseline: 149 discovered, 137 executed, 12 skipped, OK (47.048s).
- Итог `.venv-web`: 171 discovered / 156 executed / 15 skipped, OK (39.751s).
  Старое `.venv`: 171 discovered / 151 executed / 20 skipped, OK (36.772s).
  compileall, pip check (.venv-web), git diff --check прошли.
- Fake tests проверяют 5/2 budget, второй вопрос с первым ответом, empty search,
  malformed model output, неизвестные source_ids, точное URL dedupe/устойчивые ID,
  ошибку второго ответа/Resume, повтор save без повторного synthesis, SQLite
  reopen/Resume, события до завершения блокируемого Node, безопасную проекцию,
  null checkpoint и assets/labels.
- Реальные Interview HTTP tests: создание, recover/idempotency, два раунда,
  Report/download, Chat с exact pin, owner denial, payload/unfinished pin,
  streaming running до окончания Node и разные execution_id раундов.
  Финальный запуск: 3/3, OK (30.033s), включая повторное подключение SSE
  без нового Checkpoint и без нового Run.
- Существующие HTTP regressions: 10/10, OK (94.666s), на отдельной Demo 8082.
  Покрыты Research/Review/edit/cancel, Report/Chat, Assistants, Memory/isolation,
  History/Fork/pin, summary, failed Chat Resume, Streaming/reconnect/idempotency.
- Browser: форма, running answer_question до готового ответа, round 2,
  reload выполняющегося интервью, сохранённый Transcript, ошибка второго Expert,
  Resume до completed без дубликатов, раскрытие title/URL/snippet, Report → Chat.
  Проверенный доступный viewport: 760 CSS px; document scrollWidth=760,
  горизонтальное переполнение не обнаружено. Browser console error list пуст.
- Длинная тема 1430 символов без пробелов прошла два раунда: scrollWidth=760
  при clientWidth=760. Проверен keyboard Tab из выбора режима в уточнение.
- До/после browser reload совпали Thread ID и checkpoint_id в диагностике.
  Кнопка browser download нажата; наличие файла на диске браузерным инструментом
  не подтверждалось, ответ и содержимое скачивания проверены через HTTP.

## Ограничения

Полная browser E2E приёмка не объявляется завершённой: инструменты этого сеанса
не предоставляют изменение viewport. Отдельные широкая ширина 1280px и мобильная
375px и полная keyboard/focus проверка пока открыты.
CSS содержит responsive stacking/focus/wrapping, это не доказательство проверки
на всех размерах. HTTP download подтверждён; browser download проверяется отдельно.

Interview token streaming не включён: UI получает настоящие Progress Events
и завершённые сообщения. Live model/search не вызывались, качество Polza/Tavily
и фактический provider token streaming не подтверждены. Нет exactly-once для
неоконченного внешнего вызова. Ошибка source_id/формата останавливает Node без retry;
после исправления причины можно Resume. Пустой поиск честно отражается в ответе и Report.

Это локальный dev runtime с прежним разделением по user_id, не production auth.
Native серверные списки ограничены 100 записями. Полный crash recovery/multi-worker
не проверялись. Итоговый review — отдельный author self-review, без независимого
reviewer по выбранному самостоятельному способу выполнения.

Commit/push/deployment, платных запросов и автоматического включения tracing нет.
Прежние серверы не останавливались; перезапускалась только созданная для проверки
Demo 2027/8082. Практика Academy и понимание пользователя не отмечаются завершёнными.
