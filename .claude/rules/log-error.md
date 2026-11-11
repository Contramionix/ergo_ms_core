---
paths:
  - "**/logError.js"
  - "core/client/src/js/utils/**"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Логирование ошибок на клиенте

Файл: `core/client/src/js/utils/logError.js`. Общая схема логов — [`logging.mdc`](../../.cursor/rules/logging.mdc). Безопасность — [`security.mdc`](../../.cursor/rules/security.mdc), детали логов — [`security-details.mdc`](../../.cursor/rules/security-details.mdc).

`logError`, `logWarn`, `sanitizeError` подключаются **автоматически** (vite auto-import). **Не импортируй** их вручную.

## Базовый пример

```javascript
logError('Не удалось загрузить профиль', error)
logWarn('Кеш недоступен', err)
```

## Запрещено

```javascript
// BAD — в лог утекают headers, body, токены
console.error(error)
console.warn(response)

// BAD — конфиденциальные данные и идентификаторы сессии
console.log(localStorage)
console.debug({ headers: config.headers })
```

```javascript
// GOOD
logError('Ошибка сохранения', error)
```

- Дублировать санитизацию в модулях — только `logError.js`
- Логировать `Authorization`, пароли, токены, `localStorage`

## Production

- `CLIENT_LOG_LEVEL=critical` или `silent` — только DevTools; **не** отключает запись на сервер
- `CLIENT_BROWSER_LOG_ENABLED=false` — полностью отключить `client-browser.log`
- `sourcemap: false` в сборке ([`vite.config.js`](../../core/client/vite.config.js))

При `logError` ошибки уходят на `POST /api/cms/client-log/` → `logs/client-browser.log` (см. [`logging.mdc`](../../.cursor/rules/logging.mdc)). Эндпоинт требует JWT: гость и зависон до входа в этот файл **не** пишут. За nginx смотри `logs/nginx-access.log` и GET `/__client-boot` — [`nginx-spa-boot.mdc`](../../.cursor/rules/nginx-spa-boot.mdc).

Эталон использования: `core/client/src/js/api/manager.js`.

## Связанные правила

| Тема | Файл |
|------|------|
| Схема логов, env, Celery-файлы | [`logging.mdc`](../../.cursor/rules/logging.mdc) |
| Чеклист безопасности | [`security.mdc`](../../.cursor/rules/security.mdc) |
| Детали безопасности | [`security-details.mdc`](../../.cursor/rules/security-details.mdc) |
| Клиент Vue | [`client_code.mdc`](../../.cursor/rules/client_code.mdc) |
| Пустой экран за nginx | [`nginx-spa-boot.mdc`](../../.cursor/rules/nginx-spa-boot.mdc) |
