---
paths:
  - "**/permission-rules.js"
  - "**/permission-sections.js"
  - "core/client/src/modules/permissions/**"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Права на маршрутах (клиент)

Проверка на клиенте — **только для UX**. Сервер всё равно должен проверять права в API.

API path ACL в ядре: `Policy(policy_type='api')` + `ApiAccessPolicyMiddleware` / `PermissionService.check_api_access` (семантика как у URL-политик). Allow политики не заменяет `permission_classes` / `ModulePermission` на view.

## Файл правил

`modules/<имя>/client/js/permission-rules.js` — только в этой папке (вложенные пути не подхватываются).

```javascript
export default [
  {
    match: (to) => to.path?.startsWith('/<name-kebab>'),
    module: '<name>',
    permissions: ['view_something'],
    title: 'Нет доступа',
    message: 'Обратитесь к администратору.',
  },
]
```

Поля: `match`, `module`, `permissions` (достаточно одного), `title`, `message`.

Ключи в `permissions` должны совпадать с `api/permissions.py` модуля.

Подхват автоматический через `ModuleLoader`. Применение — в `routers.js` (`beforeEach`).

Ядро: `core/client/src/core/**/js/permission-rules.js`.

## Связанные правила

| Тема | Файл |
|------|------|
| Сервер — источник истины | [`security.mdc`](../../.cursor/rules/security.mdc) |
| Глобальный админ | [`global-admin.mdc`](../../.cursor/rules/global-admin.mdc) |
| Эмуляция 404 | [`route-concealment.mdc`](../../.cursor/rules/route-concealment.mdc) |
| Модули | [`modules.mdc`](../../.cursor/rules/modules.mdc) |
