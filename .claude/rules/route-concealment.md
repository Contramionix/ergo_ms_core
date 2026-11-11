---
paths:
  - "**/client/js/routes.js"
  - "core/client/src/config/routes.js"
  - "core/client/src/js/routers.js"
  - "core/client/src/js/routeConcealment.js"
  - "core/client/src/LayoutMenu.vue"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Эмуляция 404 при отказе в доступе

Если отказ в доступе не должен отличаться от несуществующего адреса, ставь **`meta.notFoundIfDenied`**. Guard рисует тот же экран 404 и **не** меняет URL. Гость с `requiresAuth` по-прежнему идёт на вход — эмуляция только для уже вошедшего.

Ядро: [`routeConcealment.js`](../../core/client/src/js/routeConcealment.js), guard в [`routers.js`](../../core/client/src/js/routers.js). Флаг действует на любой отказ (`requiresGlobalAdmin`, permission-rules, ADP).

## Кратко

- Нужна эмуляция 404 — `notFoundIfDenied: true` в `meta` маршрута
- Не редиректируй на маршрут `NotFound` и не рисуй свой 404 в модуле

## Обязательно

1. Вместе с проверкой, кому страница вообще нужна (`requiresAuth`, `requiresGlobalAdmin` или правило в `permission-rules.js`).
2. Не `{ name: 'NotFound', params: { pathMatch } }`: catch-all снова совпадёт с живым путём, и служебный маршрут откроется.

## Запрещено

```javascript
// BAD — карточка «нет доступа» выдаёт, что адрес настоящий
meta: { requiresAuth: true, requiresGlobalAdmin: true }

// BAD — именованный NotFound на существующий path
return { name: 'NotFound', params: { pathMatch: to.path.substring(1).split('/') } }
```

## Базовый пример

```javascript
// modules/<name>/client/js/routes.js
export default {
  ModuleLab: {
    path: '/<name>/lab',
    name: 'ModuleLab',
    component: '@/modules/<name>/client/pages/LabPage.vue',
    meta: {
      titleKey: '<name>.routes.lab',
      requiresAuth: true,
      requiresGlobalAdmin: true,
      notFoundIfDenied: true,
    },
  },
}
```

## Связанные правила

| Тема | Файл |
|------|------|
| Guards и порядок beforeEach | [`route-guards.mdc`](../../.cursor/rules/route-guards.mdc) |
| UX-права на маршрутах | [`permission_rules.mdc`](../../.cursor/rules/permission_rules.mdc) |
| Глобальный админ | [`global-admin.mdc`](../../.cursor/rules/global-admin.mdc) |
