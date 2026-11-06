---
paths:
  - "modules/*/api/apps.py"
  - "modules/*/api/integrations.py"
  - "modules/*/api/celery_config.py"
  - "modules/*/api/celery_beat_config.py"
  - "modules/*/api/permission_catalog.py"
  - "modules/*/api/schema.yaml"
  - "modules/*/api/bridge_manifest.yaml"
  - "modules/*/api/search_indexes.py"
  - "modules/*/client/js/routes.js"
  - "modules/*/client/js/integrations.js"
  - "modules/*/client/js/theme-defaults.js"
  - "modules/*/client/js/endpoints.js"
  - "modules/*/client/js/permission-rules.js"
  - "modules/*/client/js/routeGuard.js"
  - "modules/*/client/js/locales.js"
  - "modules/*/integrations.yaml"
  - "modules/*/process_roles.yaml"
  - "modules/*/host_lifecycle.yaml"
  - "modules/*/packages.yaml"
  - "modules/*/huggingface_models.yaml"
  - "modules/*/runtime_requirements.yaml"
  - "modules/*/model_providers.yaml"
  - "modules/*/vscode.tasks.yaml"
  - "modules/*/task_footprint.yaml"
  - "modules/*/task_restart.yaml"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Модули

Пользовательский каталог возможностей модуля (hook’и, мост, install-services, packages): [`.docs/modules.md`](../../.docs/modules.md).

## Структура

```
modules/<имя>/
├── api/
│   ├── apps.py              # обязательно для регистрации
│   ├── models.py, views.py, urls.py, serializers.py
│   ├── tasks.py             # фоновые задачи (если нужны)
│   ├── celery_config.py     # очереди Celery (если нужны)
│   ├── integrations.py      # операции для моста (если нужны)
│   ├── bridge_manifest.yaml # ops/groups при MODULE_RUNTIME=microservice
│   ├── schema.yaml          # схема PostgreSQL m_<name>, isolated
│   ├── search_indexes.py    # индексы поиска (uid с префиксом модуля)
│   └── user_guides/         # шпаргалки пакета knowledge/ (необязательно)
├── client/
│   ├── js/
│   │   ├── routes.js        # страницы (если есть UI)
│   │   ├── endpoints.js     # адреса API для клиента (если нужны)
│   │   ├── permission-rules.js
│   │   ├── routeGuard.js      # опционально: guard для Vue Router
│   │   ├── integrations.js  # операции моста на клиенте
│   │   ├── locales.js         # каталоги ru/en модуля (i18n.mdc)
│   │   └── theme-defaults.js  # обязателен, если у модуля отдельная палитра (themes.mdc)
│   ├── styles/
│   │   └── theme-bootstrap.scss  # обязателен вместе с theme-defaults.js
│   ├── pages/ или components/
│   └── ui/                  # общий UI-kit (по образцу других модулей с client/ui)
├── mcp/                     # MCP-сервер для Cursor (необязательно)
├── .cursor/rules/           # правила Cursor модуля (*.mdc; необязательно)
├── AGENTS.md                # короткий fallback для агента (обязательно)
├── BEHAVIOR.md              # как должен работать модуль (нормы из чата; не обязательно)
├── README.md                # обзор для человека (обязательно)
├── ergoms.conf              # команды модуля (необязательно)
├── ergoms.help.yaml         # справка для ergoms help module (если есть ergoms.conf)
├── process_roles.yaml       # роли процессов для ergoms resource-usage (если есть свой демон)
├── celery_workers.yaml      # именованные воркеры модуля: id, очереди, hostname (если видов несколько)
├── task_footprint.yaml      # footprint задач для ergoms celery-balance (если есть Celery)
├── task_restart.yaml       # что делать с задачей после перезапуска воркера: hold / drop / requeue
├── host_lifecycle.yaml      # install/uninstall/stop демона в install-services и тестах (если есть служба/процесс)
├── packages.yaml            # portable-пакеты в virtual_env/packages (если модуль ставит бинарники)
├── huggingface_models.yaml  # снимки Hugging Face в virtual_env/trained_models/huggingface/
├── runtime_requirements.yaml # инструменты, модели и Python-группы (версия 1)
├── model_providers.yaml     # адаптер локального индекса моделей (если модуль — провайдер)
├── vscode.tasks.yaml        # задачи Run Task + include_in setup-full/start-all (необязательно)
├── cursor_hooks.yaml        # команды на события Cursor, диспетчер ядра без имён модулей (необязательно)
├── integrations.yaml        # depends: requires (обязательные) / extends (опциональные)
```

Папка клиента: `client/js/`, **не** `client/src/js/`.

Ядро **не импортирует** домен модуля. Допустимо только сканирование hook-файлов с фиксированным именем (`importlib` / `import.meta.glob`), не `from modules.<name>.api.models import …`.

| Область ядра | Hook | Эталон |
|--------------|------|--------|
| Django apps | `apps.py` | [`auto_config.py`](../../core/api/src/core/utils/auto_api/auto_config.py) |
| Права ADP | `permission_catalog.py` | [`permission_catalog.py`](../../core/api/src/core/cms/adp/services/permission_catalog.py) |
| Celery | `celery_config.py`, `celery_workers.yaml` | [`celery/manager.py`](../../core/api/src/core/utils/celery/manager.py), [`module_queues.py`](../../core/api/src/core/utils/celery/module_queues.py) |
| Клиент: routes / endpoints / integrations | `client/js/*` | [`ModuleLoader.js`](../../core/client/src/modules/core/ModuleLoader.js) |
| Тема | `theme-defaults.js` | [`ThemeDefaultsManager.js`](../../core/client/src/modules/themes/ThemeDefaultsManager.js) |
| i18n | `locales.js` | [`LocaleManager.js`](../../core/client/src/modules/i18n/LocaleManager.js) |
| Route guards | `routeGuard.js` | [`RouteGuardsManager.js`](../../core/client/src/modules/routing/RouteGuardsManager.js) |
| LayoutPlugin | `layout.plugin_registry` | [`layoutPluginRegistry.js`](../../core/client/src/integrations/layoutPluginRegistry.js) |
| Session-scope | `session_scope.module_context` | [`sessionScopedModuleContext.js`](../../core/client/src/integrations/sessionScopedModuleContext.js) |
| Claims при логине | `session.restore_claims` | [`views_auth.py`](../../core/api/src/core/cms/adp/views_auth.py) |
| Меню CMS | миграции меню + `menu.catalog` | [`restore_menu.py`](../../core/api/src/core/cms/management/commands/restore_menu.py) |
| resource-usage | `process_roles.yaml` | [`process-roles.mdc`](../../.cursor/rules/process-roles.mdc) |
| Celery balance | `task_footprint.yaml` | [`celery-balance.mdc`](../../.cursor/rules/celery-balance.mdc) |
| Задачи после перезапуска | `task_restart.yaml` | [`celery-restart.mdc`](../../.cursor/rules/celery-restart.mdc) |
| OS-службы | `host_lifecycle.yaml` | [`host-lifecycle.mdc`](../../.cursor/rules/host-lifecycle.mdc) |
| Portable-пакеты | `packages.yaml` | [`packages.mdc`](../../.cursor/rules/packages.mdc) |
| Снимки Hugging Face | `huggingface_models.yaml` | [`huggingface-models.mdc`](../../.cursor/rules/huggingface-models.mdc) |
| Индекс моделей и runtime | `runtime_requirements.yaml`, `model_providers.yaml` | [runtime-models.md](../../.docs/runtime-models.md) |
| Run Task / setup-full | `vscode.tasks.yaml` | [`module-vscode-tasks.mdc`](../../.cursor/rules/module-vscode-tasks.mdc) |
| События Cursor | `cursor_hooks.yaml` | [`cursor_module_hooks.py`](../../core/deployment/scripts/cursor_module_hooks.py) |
| Схема PostgreSQL | `api/schema.yaml` | [`modularization.mdc`](../../.cursor/rules/modularization.mdc) |
| HTTP-мост | `api/bridge_manifest.yaml` | [`modularization.mdc`](../../.cursor/rules/modularization.mdc) |
| Поиск | `search_indexes.py` | [`discovery.py`](../../core/api/src/core/search/discovery.py) |

Правила агента Cursor для модуля — в `.cursor/rules/*.mdc` (globs `modules/<имя>/**`) и кратко в `AGENTS.md`. Cursor читает вложенные правила сам, без копии плагина. Платформенные правила остаются в корневом `.cursor/rules/`. Подробности: [`module-cursor-rules.mdc`](../../.cursor/rules/module-cursor-rules.mdc).

При правках модуля **обновляй его документацию** (`AGENTS.md`, `.mdc`, `README.md`, help) вместе с кодом — [`module-docs.mdc`](../../.cursor/rules/module-docs.mdc). Устойчивые пожелания из чата («должно быть так / не так») — в `BEHAVIOR.md` по [`module-behavior.mdc`](../../.cursor/rules/module-behavior.mdc). Это исключение из общего «не пиши docs без просьбы» в [`docs.mdc`](../../.cursor/rules/docs.mdc).

Учёт модульного процесса в `ergoms resource-usage` — только через `process_roles.yaml` ([`process-roles.mdc`](../../.cursor/rules/process-roles.mdc)); не правь классификатор ядра ради одного модуля.

Install/uninstall/stop модульного демона в `ergoms install-services` / `uninstall-services` и Windows-тестах deployment — только через `host_lifecycle.yaml` ([`host-lifecycle.mdc`](../../.cursor/rules/host-lifecycle.mdc)).

Portable-бинарники модуля (ollama, ffmpeg и т.п.) — только через `packages.yaml` и `ergoms package-install` ([`packages.mdc`](../../.cursor/rules/packages.mdc)); не дублируй download в Django management и не хардкодь имена модулей в ядре.

Снимки Hugging Face (`org/name`) — только через `huggingface_models.yaml` и `ergoms pull-huggingface-models` ([`huggingface-models.mdc`](../../.cursor/rules/huggingface-models.mdc)); веса в `virtual_env/trained_models/huggingface/`, не в `ollama_models.yaml`, не в `~/.cache` и не в кэш модуля.

Задачи VS Code / Cursor (Run Task) и участие в **Setup Full** / **Start All** — только через `vscode.tasks.yaml` (`include_in: setup-full` / `start-all`): hook модульности, не правка монолита ядра. Подробности — [`module-vscode-tasks.mdc`](../../.cursor/rules/module-vscode-tasks.mdc); формат shell-задач ядра — [`vscode-tasks.mdc`](../../.cursor/rules/vscode-tasks.mdc).

Команды модуля на событие Cursor (`stop` и другие) объявляются в `cursor_hooks.yaml`. Диспетчер [`cursor_module_hooks.py`](../../core/deployment/scripts/cursor_module_hooks.py) обходит каталоги модулей, читает этот файл и запускает команду из каталога модуля. Имя модуля в ядре не пишется. Ответ команды с `followup_message` возвращается агенту.

Вложенные подприложения (`client/<раздел>/js/routes.js`) подхватываются для маршрутов и `integrations.js`. Файлы `endpoints.js`, `permission-rules.js` — только из `client/js/` (или re-export оттуда).

## Регистрация на сервере

Зависимости модулей — корневой [`integrations.yaml`](../../core/api/src/core/utils/auto_api/module_integrations.py) (имена папок `modules/<name>`):

```yaml
# modules/<name>/integrations.yaml
requires:          # обязательные: нет модуля → потребитель не загружается (WARNING), остальные стартуют
  - <provider>
extends:           # опциональные: нет модуля → старт OK; фичи через bridge.has / default
  - <optional_enhancer>
```

- `requires` — обязательная интеграция и дуга порядка загрузки (зависимость раньше потребителя). Нет зависимости (отключена или нет в `modules/`) — потребитель пропускается, Django не падает целиком. Ключ в `BRIDGE_SERVICE_URLS` (или имя в `MICROSERVICE_MODULES`) закрывает `requires` без локальной папки: сосед доступен по HTTP-мосту. Удалённое имя не заноси в `MICROSERVICE_MODULES` на этом хосте.
- `extends` — расширяющая интеграция; в топсорт **не** входит (иначе цикл, когда A.`extends` B и B.`requires` A).
- Только односторонние `requires`: мягкий `bridge.has` в обе стороны не дублируй в `requires`.

```python
# api/apps.py
class MyModuleConfig(AppConfig):
    name = 'modules.<name>.api'

    def ready(self):
        from . import integrations  # если есть мост
```

Регистрация в `INSTALLED_APPS` вручную не нужна — находит `ModuleDiscoverer` + [`module_load_order.py`](../../core/api/src/core/utils/auto_api/module_load_order.py).

**Lean schema CLI** (`migrate` / `makemigrations`): у `modules.*` пропускается `ready()` и **не** подключаются URL модулей — схема БД без runtime-моста.

## Регистрация на клиенте

Файлы из `client/js/` подхватывает `ModuleLoader`. Регистрировать вручную не нужно.

Не все файлы обязательны: бывает только API, только права на маршруты, маршруты без меню.

## Живой шаблон модуля

Канонический эталон структуры и UI модуля — `modules/module_template`.

Если в ядре появляется **новый переиспользуемый паттерн для модулей** (компонент из [`components.mdc`](../../.cursor/rules/components.mdc), composable списков, confirm/toast, hook-файл, platform-контракт bridge), добавь **рабочее демо** в `module_template` и запись в `client/js/core_patterns.json`. Проверка: `ergoms module_template:patterns-check`. Правило модуля: `modules/module_template/.cursor/rules/module-template-living.mdc`.

Не считай README достаточным демо — нужен исполняемый пример в шаблоне.

## UI на клиенте

Выпадающие списки — **только** `SelectBox` из ядра (`@/components/SelectBox.vue`). Не создавай в модуле свой `<select>` или выпадающий список для обычного выбора. Подробности: [`select-box.mdc`](../../.cursor/rules/select-box.mdc).

**Настройки клиента модуля** — `CLIENT_<МОДУЛЬ>_*` в корневом `.env` или `modules/<имя>/.env`, маппинг в [`vite.config.js`](../../core/client/vite.config.js) (`import.meta.env.CLIENT_*`). В модуле читай через **локальный** `client/js/clientEnv.js`, не через ядровой `clientEnv.js` и не `VITE_*`.

**LayoutPlugin и offcanvas** — регистрация в `client/js/integrations.js` через группу `layout.plugin_registry` (см. [`layoutPluginRegistry.js`](../../core/client/src/integrations/layoutPluginRegistry.js)). Ядро не хранит маппинг `route_name → module`. Файл `client/LayoutPlugin.vue` не импортируй на верхнем уровне библиотеки, которые при загрузке модуля вызывают `.register` (графики и подобные). Иначе сбой плагина ломает оболочку кабинета; выноси в `defineAsyncComponent`.

**Session-scoped модули** — группа моста `session_scope.module_context`. Регистрация в `client/js/integrations.js`: `bridge.provideMany(SESSION_SCOPED_MODULE_CONTEXT_GROUP, moduleKey, { pathPrefix, homeRoute, ... })` — **без import из модуля-владельца scope**. Хелперы — [`sessionScopedModuleContext.js`](../../core/client/src/integrations/sessionScopedModuleContext.js), session-scope guard — [`sessionScopeGuard.js`](../../core/client/src/js/session/sessionScopeGuard.js), активность scope — [`sessionScopeGating.js`](../../core/client/src/integrations/sessionScopeGating.js). Каталог контрактов — [`module-contracts.mdc`](../../.cursor/rules/module-contracts.mdc). Домен владельца scope (welcome API, store) — в `modules/<host_module>/client/js/` (свой `*Guard.js`), не в ядре.

**Модульные темы** — только hook `client/js/theme-defaults.js` + `POST settings/themes/sync-module-defaults/`; в ядре **нет** builtin-палитр модулей.

Пункты бокового меню — **миграция API** (`MenuMigrationHelper`, эталон `modules/<name>/api/migrations/*_add_menu.py`); маршруты — `client/js/routes.js`. Процесс модуля отдаёт дерево через `menu.catalog`, ядро пишет его в свои таблицы. Порядок и видимость — в CMS. Подробности: [`menu.mdc`](../../.cursor/rules/menu.mdc).

Эмуляция 404 при отказе в доступе — `meta.notFoundIfDenied` в `routes.js`, не свой редирект на маршрут `NotFound` и не карточка «нет доступа». [`route-concealment.mdc`](../../.cursor/rules/route-concealment.mdc)

Пункты выпадающего меню пользователя в шапке (`UserMenu`) — через `bridge.provideMany` в группе `header.userMenu.items`. Эталон: `modules/<name>/client/js/headerUserMenu.js`, подключается из `integrations.js`. Сбор в ядре — [`headerUserMenu.js`](../../core/client/src/integrations/headerUserMenu.js). Это **не** боковое меню: sidebar — миграции API, шапка — ModuleBridge. Иконка — строка Lucide PascalCase (`icon: 'Building2'`), не Vue-компонент — [`icons.mdc`](../../.cursor/rules/icons.mdc).

Пункты меню приложений (`AppsMenu` в toolbar) — через `bridge.provideMany` в группе `apps.menu.items`. Эталон: `modules/<name>/client/js/appsMenu.js`, подключается из `integrations.js`. Имя группы берите из `@/integrations/moduleContracts.js`, не из `appsMenu.js`: иначе remote тянет сборщик оболочки. Сбор в ядре — [`appsMenu.js`](../../core/client/src/integrations/appsMenu.js). Кнопка скрыта без пунктов. Для UX-ограничения укажите `permissionModule` + `permission` (глобальный админ видит через `hasModulePermission`); `isVisible` — только если одной пары прав мало. Иконка — строка (`icon: 'Bot'`), рендер в ядре через `LucideIcon`.

Бренд в шапке сайдбара / mobile header — опционально через `shell.sidebar_brand` ([`sidebarBrand.js`](../../core/client/src/integrations/sidebarBrand.js)): модуль регистрирует `{ id, component, match?, to?, measureText? }`; без match ядро оставляет `SiteWordmark`.

Плавающие виджеты оболочки (мини-чат и т.п.) — группа `shell.floating_widgets` (`{ id, component, order?, isVisible? }`), хост [`FloatingWidgetsHost`](../../core/client/src/components/FloatingWidgetsHost.vue) в `LayoutMenu`. Компонент виджета — `markRaw` / `defineAsyncComponent`, не сырой объект в `ref`. Не использовать `LayoutPlugin` ради плавающего UI.

Бейдж справа в строке бокового меню — группа `menu.item_trailing` (`{ match: { routeName }, count, title?, route?, order? }`). Ядро рисует число на совпавшем пункте и на родительских группах, слева от стрелки; ноль скрыт. Имя группы берите из `@/integrations/moduleContracts.js`. Сбор — [`menuItemTrailing.js`](../../core/client/src/integrations/menuItemTrailing.js).

## Темы оформления модуля

Подробности — [`themes.mdc`](../../.cursor/rules/themes.mdc). Кратко:

| Нужна отдельная палитра модуля? | Действие |
|--------------------------------|----------|
| **Нет** — хватает цветов сайта | Стили через `var(--ui-*)`, hook темы не создавай |
| **Да** — свой accent, фоны, неоновые токены | **Только** через hook + редактор ядра |

### Обязательно (модуль с отдельной палитрой)

1. `client/js/theme-defaults.js` — дефолты и **пара** light+dark (`modulePair`, `systemThemes` с двумя `base_theme`)
2. `client/styles/theme-bootstrap.scss` — алиасы `--<module>-*`; импорт в `routes.js`
3. `useModuleThemeMode('module_key')` вместо `useThemeMode()` на страницах модуля
4. Цвета в SCSS — `var(--color-*)` / `var(--<module>-*)`, не hex и не `$palette-*` для настраиваемых полей
5. Правки палитры админом — только `/settings/themes` → область модуля, **не** UI в модуле

Эталон: `modules/<name>/client/js/theme-defaults.js`, `modules/<name>/client/styles/theme-bootstrap.scss`.

`theme-defaults.js` подхватывает `ModuleLoader` (glob prebuild). Ядро не импортирует бизнес-код модуля — только hook, как `integrations.js` (см. [`struct.mdc`](../../.cursor/rules/struct.mdc)).

### Запрещено

- Локальные SCSS-палитры с hex (`$neon-cyan`, `$dark-bg-*`) **вместо** hook, если палитра должна настраиваться
- Свой редактор / настройки темы в модуле
- `useThemeMode()` на страницах модуля с `theme-defaults.js`
- Teleport модалок в `body` (ломает `ModuleThemeScope`)

## Имена

- Папка модуля: `kebab-case` (`<name-kebab>`)
- В Python: `snake_case` (`<name>`)

## Импорты

**Сервер:** внутри модуля — относительные; из ядра — `from src.core...`; из другого модуля — **запрещено**.

**Ядро → модуль:** бизнес-код модуля — **запрещён**; hook-файлы для discovery — **допустимы** через инфраструктуру ядра (таблица выше).

**Клиент:** из ядра — `@/...`; из другого модуля — **запрещено**.

## Мост между модулями (ModuleBridge)

Единственный способ связи модулей друг с другом.

**Сервер** — `core/api/src/core/integrations/`:

```python
from src.core.integrations import bridge

# вызов
ids = bridge.call('<name>.get_user_entity_ids', user=request.user, default=[])

# регистрация (в modules/<name>/api/integrations.py)
@bridge.provide_op('<name>.get_user_entity_ids')
def _handler(user):
    ...
```

Имена операций: `'модуль.действие'`. Если провайдера нет — `call` вернёт `default`.

Платформенный op ядра (логин) — opaque dict claims, ключи ядру неизвестны:

```python
# core/.../views_auth.py
restore_claims = bridge.call(SESSION_RESTORE_CLAIMS, user=user) or {}

# modules/<host>/api/integrations.py
@bridge.provide_op(SESSION_RESTORE_CLAIMS)
def _restore_session_claims(*, user=None, **_):
    return get_restorable_session_claims(user)
```

**Запрещено** на уровне модуля (import-time):

```python
# BAD — class-base / Meta от результата bridge.call (на migrate bridge пуст → None.Meta)
Base = bridge.call('<provider>.get_base_serializer_cls')
class MySerializer(Base):
    class Meta(Base.Meta):
        pass

# GOOD — resolve в момент использования (после ready провайдера)
def get_my_serializer_class():
    base = bridge.call('<provider>.get_base_serializer_cls')
    ...
```

**Клиент** — `@/integrations/ModuleBridge.js`, регистрация в `client/js/integrations.js`.

В `integrations.js` на верхнем уровне импортируй **только** `bridge`. Остальное — ленивый `import()` внутри обработчика (иначе цикл при старте).

## Celery в модуле

- Задачи: `api/tasks.py`
- Конфиг: `api/celery_config.py`, маршрут `'modules.<имя>.api.tasks.*'`
- Несколько воркеров: `celery_workers.yaml` в корне модуля. Запуск одного — `ergoms start-worker --module=<имя> --worker=<id>`
- Footprint (опционально): `task_footprint.yaml` — [`celery-balance.mdc`](../../.cursor/rules/celery-balance.mdc)

## Git

Модули — отдельные репозитории (submodule). Обновление: `git submodule update`.

## Глобальный админ в модулях

Роль «Администратор» и `is_superuser` **эквивалентны** по доступу в приложении. В модулях не проверяй `is_superuser` / `is_staff` напрямую — только `PermissionService.is_admin(user)` или `check_module_permission` (он уже пропускает глобального админа). Подробности — [`global-admin.mdc`](../../.cursor/rules/global-admin.mdc).

## Запрещено

- Менять ядро ради одного модуля
- Прямые импорты между модулями
- Hardcoded имена модулей в ядре (см. [`struct.mdc`](../../.cursor/rules/struct.mdc))
- Регистрировать модуль вручную в настройках
- Отдельная палитра модуля без `theme-defaults.js` и редактора ядра (см. [`themes.mdc`](../../.cursor/rules/themes.mdc))

## Связанные правила

| Тема | Файл |
|------|------|
| Platform-контракты | [`module-contracts.mdc`](../../.cursor/rules/module-contracts.mdc) |
| Темы оформления, hook, ModuleThemeScope | [`themes.mdc`](../../.cursor/rules/themes.mdc) |
| Изоляция ядра | [`core-module-isolation.mdc`](../../.cursor/rules/core-module-isolation.mdc) |
| Архитектура | [`struct.mdc`](../../.cursor/rules/struct.mdc) |
| API, ViewSet | [`api_code.mdc`](../../.cursor/rules/api_code.mdc) |
| Миграции `api/migrations/` | [`django-migrations.mdc`](../../.cursor/rules/django-migrations.mdc) |
| Клиент, маршруты | [`client_code.mdc`](../../.cursor/rules/client_code.mdc) |
| Celery в модуле | [`celery.mdc`](../../.cursor/rules/celery.mdc) |
| Безопасность, public_id | [`security.mdc`](../../.cursor/rules/security.mdc) |
| Уведомления, аудит | [`notifications.mdc`](../../.cursor/rules/notifications.mdc), [`audit.mdc`](../../.cursor/rules/audit.mdc) |
| Человекочитаемо | [`.docs/architecture.md`](../../.docs/architecture.md) |
| Боковое меню | [`menu.mdc`](../../.cursor/rules/menu.mdc) |
| Иконки Lucide | [`icons.mdc`](../../.cursor/rules/icons.mdc) |
| Справка ergoms модуля | [`ergoms-module-help.mdc`](../../.cursor/rules/ergoms-module-help.mdc) |
| Роли процессов (resource-usage) | [`process-roles.mdc`](../../.cursor/rules/process-roles.mdc) |
| Host lifecycle (тесты deployment) | [`host-lifecycle.mdc`](../../.cursor/rules/host-lifecycle.mdc) |
| Portable-пакеты (virtual_env/packages) | [`packages.mdc`](../../.cursor/rules/packages.mdc) |
| Дата рождения и возраст пользователя | [`user-birth-date.mdc`](../../.cursor/rules/user-birth-date.mdc) |
| Карточка человека без учётки (Person) | [`person.mdc`](../../.cursor/rules/person.mdc) |
| Модульные задачи Run Task | [`module-vscode-tasks.mdc`](../../.cursor/rules/module-vscode-tasks.mdc) |
| Формат задач ядра (tasks.json) | [`vscode-tasks.mdc`](../../.cursor/rules/vscode-tasks.mdc) |
| Правила Cursor модуля | [`module-cursor-rules.mdc`](../../.cursor/rules/module-cursor-rules.mdc) |
| Документация модуля (AGENTS/README) | [`module-docs.mdc`](../../.cursor/rules/module-docs.mdc) |
| Вынос в отдельный процесс / схему | [`modularization.mdc`](../../.cursor/rules/modularization.mdc) |
| MCP модуля | [`mcp.mdc`](../../.cursor/rules/mcp.mdc) |
| Балансировщик Celery | [`celery-balance.mdc`](../../.cursor/rules/celery-balance.mdc) |
| Стиль правил и docs | [`writing-docs-and-rules.mdc`](../../.cursor/rules/writing-docs-and-rules.mdc) |
| Redis, nginx (prod) | [`deployment-infra.mdc`](../../.cursor/rules/deployment-infra.mdc) |
