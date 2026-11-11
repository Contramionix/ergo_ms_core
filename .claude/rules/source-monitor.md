---
paths:
  - "**/monitor/**"
  - "**/source_monitor/**"
  - "**/useSourceMonitor.js"
  - "**/SourceRunActions.vue"
  - "**/LiveRateChart.vue"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Мониторинг источников

Общий каркас экрана «источники → запуск / остановка / снимок» живёт в ядре. Модуль оставляет доменные карточки, реестр источников и постановку своих Celery-задач.

## Кратко

- Сервер: `src.core.source_monitor` — `claim` / `attach` / `release`, `serve_snapshot`, `day_totals` в `live_metrics`
- Клиент: `useSourceMonitor`, `SourceRunActions`, `LiveRateChart`
- Имена установленных модулей в ядре не пиши — только `namespace` и `source_id`
- Тяжёлый `build_snapshot` — только из Celery Beat модуля, не в потоке GET

## Обязательно

- Перед `apply_async` — `claim(namespace, source_id)`; id из результата — `attach`; при отказе или падении постановки — `release`
- Опрос Celery `inspect` — сверка. Молчание опроса не значит «свободен» и не снимает claim
- `GET …/snapshot/` отдаёт кэш или оболочку через `serve_snapshot`; устаревший снимок не пересобирай в запросе. Оболочку без чисел в кэш не пиши
- Суточные итоги метрик — `day_totals` (часовые ключи), не сумма 1440 минутных бакетов на каждый запрос
- Клиент: опрос снимка. Пока это оболочка без чисел или снимок устарел — каждые 2 секунды, иначе каждые 5. Оболочку с нулями на экран не клади. `client.on('parser_monitor_snapshot')` без `subscribe` — тема модуля на API оболочки часто даёт 403
- Кнопки — `SourceRunActions` с `label-prefix` локали модуля; график — ленивый `LiveRateChart` из ядра
- «Запускаю…» держи до смены статуса в снимке

## Запрещено

```python
# BAD — пустой inspect как «можно стартовать снова»
if not inspect.active():
    task.apply_async(...)

# BAD — полный снимок в GET
def get(self, request):
    return Response(build_snapshot())
```

```javascript
# BAD — свой SourceActions и setInterval без подписки на тему
```

```python
# GOOD
if not claim(NAMESPACE, source_id):
    return refused('уже идёт')
try:
    result = task.apply_async(...)
    attach(NAMESPACE, source_id, [result.id])
except Exception:
    release(NAMESPACE, source_id)
    raise
```

## Связанные правила

| Тема | Файл |
|---|---|
| Realtime, темы | [`realtime.mdc`](../../.cursor/rules/realtime.mdc) |
| UI-компоненты | [`components.mdc`](../../.cursor/rules/components.mdc) |
| Celery | [`celery.mdc`](../../.cursor/rules/celery.mdc) |
| Производительность клиента | [`client-perf.mdc`](../../.cursor/rules/client-perf.mdc) |
