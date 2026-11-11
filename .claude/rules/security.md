<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Безопасность ERGO MS

Перед правками auth, API, прав, файлов, env, CORS, cookies или логов сверься с этим правилом. Примеры — [`security-details.mdc`](../../.cursor/rules/security-details.mdc).

- Секреты только в `.env`, не в коде, git и чате. Серверные ключи не попадают в бандл клиента.
- Токены и контекст сессии — через `tokenStorage.js`, не в localStorage. JWT не в query WebSocket.
- Снаружи `public_id` (UUID), не числовой id из БД: ни в URL, ни в query, ни в browser storage.
- API проверяет права сам. Эндпоинт по умолчанию требует JWT (`BaseAPIView` / `BaseModelViewSet`). Публичный — только `BaseAPIViewPublicMixin` и строка в allowlist.
- Файлы — через media_api, не `/media/` на основном API.
- Ошибки клиента — `logError`, не `console.error` объекта axios. В логах API нет credentials.
- Prod: `DEBUG=False`, cookies HttpOnly, Secure и SameSite, без sourcemap.
- Железо хоста в git не пиши — [`no-host-fingerprint.mdc`](../../.cursor/rules/no-host-fingerprint.mdc). Исключение по безопасности молча не делай.
