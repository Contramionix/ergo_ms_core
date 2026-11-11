---
paths:
  - "modules/**/README.md"
  - "modules/**/AGENTS.md"
  - "modules/**/BEHAVIOR.md"
  - "modules/**/.cursor/rules/**"
  - "modules/**/ergoms.help.yaml"
  - "modules/**/ergoms.conf"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Документация модуля

При правках в `modules/<name>/` **держи документацию модуля в актуальном состоянии** вместе с кодом. Не оставляй устаревшие контракты, запреты и команды.

Платформенные правила ядра сюда не дублируй — только домен и границы модуля. Стиль текста — [`writing-docs-and-rules.mdc`](../../.cursor/rules/writing-docs-and-rules.mdc). Правила Cursor модуля — [`module-cursor-rules.mdc`](../../.cursor/rules/module-cursor-rules.mdc).

## Кратко

| Аудитория | Файл | Содержание |
|-----------|------|------------|
| Агент (кратко) | `AGENTS.md` | куда смотреть, обязательно / запрещено, ключевые команды |
| Агент (детали) | `.cursor/rules/*.mdc` | globs `modules/<name>/**`, чеклист, BAD/GOOD |
| Как должен работать | `BEHAVIOR.md` | устойчивые нормы из чата; если файл стал оглавлением, текст темы лежит в `behavior/` — [`module-behavior.mdc`](../../.cursor/rules/module-behavior.mdc) |
| Люди | `README.md` | назначение, зависимости, настройка `.env`, команды ergoms |
| CLI | `ergoms.help.yaml` (+ `locales/<lang>/`) | справка `ergoms help module` |
| Учебный эталон | `modules/module_template/` | HOWTO + living patterns |

Не каждый модуль обязан иметь длинный HOWTO — только если сценарии сложнее, чем README.

## Когда обновлять (обязательно)

После изменения **обнови соответствующие файлы в том же PR / той же задаче**, если затронуто:

1. **Публичный контракт** — ops ModuleBridge, REST URL, query-параметры, поля ответа
2. **Безопасность** — права ADP, ownership, media path, whitelist конфигов, запрет прямых импортов/URL
3. **Интеграции** — `integrations.yaml` (`requires` / `extends`), транспорт к другому модулю
4. **Запуск / установка** — `vscode.tasks.yaml`, `packages.yaml`, `host_lifecycle.yaml`, `process_roles.yaml`, `task_footprint.yaml`, Celery
5. **CLI** — новые/удалённые команды в `ergoms.conf` → `ergoms.help.yaml` и overlays
6. **Клиентские hooks** — routes, endpoints, theme-defaults, proxy вместо чужого REST
7. **Вынос процесса / данных** — `api/schema.yaml`, `api/bridge_manifest.yaml`
8. **Нормы из чата** — новое или изменённое «так / не так» → `BEHAVIOR.md` ([`module-behavior.mdc`](../../.cursor/rules/module-behavior.mdc))

Мелкий внутренний рефактор без смены поведения — документацию не раздувай.

## Обязательный минимум модуля

| Артефакт | Когда |
|----------|--------|
| `AGENTS.md` | всегда (fallback без sync `.mdc`) |
| `README.md` | всегда (для человека: назначение, зависимости, `.env`, ergoms) |
| `BEHAVIOR.md` | когда в чате появилось устойчивое «так / не так»; пустой файл не создавай |
| `.cursor/rules/<topic>.mdc` | доменные запреты и эталоны кода |
| `.env.example` | есть модульные переменные окружения |
| `ergoms.help.yaml` | есть `ergoms.conf` |
| `api/user_guides/*.md` | необязательно: сценарии, которых нет в разметке (несколько шагов подряд). Экраны, поля и кнопки ядро само кладёт в пакет `knowledge/` при `publish-knowledge-packs` |
| `user_description` в `PERMISSION_CATALOG` | необязательно: 1–3 предложения «зачем модуль» для пользователя |

Инфра-модуль без UI может не иметь `client/` и клиентских разделов в README — опиши ops и bridge. Пустой submodule без `api/apps.py` и без `client/` не считается установленным: `README.md` и `AGENTS.md` для него не требуются, пока каталог не checkout’нут. Проверка: `ergoms core-rules-check`.

## Структура

**`AGENTS.md`** — короткий указатель (ориентир до ~40 строк): роль модуля → куда смотреть → запрещено → обязательно → команды. Если есть `BEHAVIOR.md`, в «Куда смотреть» одна строка на этот файл.

**`BEHAVIOR.md`** — сводка, как должен работать модуль по словам пользователя в чате. Не копия README и не platform-правила ядра. Когда писать и как формулировать — [`module-behavior.mdc`](../../.cursor/rules/module-behavior.mdc).

**`.mdc` модуля** — одна тема на файл; frontmatter:

```yaml
---
description: <name> — тема и ключевые сущности
globs:
  - "modules/<name>/**"
alwaysApply: false
---
```

**`README.md`** — для человека: что делает модуль, от каких модулей зависит, как настроить, как запустить через ergoms, куда смотреть в коде. Без копипасты всего [`modules.mdc`](../../.cursor/rules/modules.mdc).

## Запрещено

- Править код модуля и **не** обновить устаревший запрет/контракт в `AGENTS.md` / `.mdc` / README
- Игнорировать `BEHAVIOR.md` при работе с модулем или не записать туда новое устойчивое пожелание из чата
- Класть домен модуля только в корневой `.cursor/rules/` (новые доменные правила — в модуле)
- `alwaysApply: true` на модульных `.mdc`
- Дублировать platform-правила ядра вместо ссылки
- Документировать `python manage.py` / прямой `npm` / `pip` как основной способ — только `ergoms`
- Секреты, пароли, реальные значения из `.env` в примерах

## Базовый пример (синхронизация)

```text
# BAD — в коде убрали клиентский base_url, в AGENTS.md всё ещё «можно передать URL Ollama»
# GOOD — в AGENTS.md / .mdc: ollama_config whitelist; base_url только из .env модуля
```

```text
# BAD — новый bridge op без строки в AGENTS.md «Мост наружу»
# GOOD — ops перечислены или указан файл integrations.py + ключевые ограничения (user, media path)
```

## Эталоны

| Тип | Путь |
|-----|------|
| Живой шаблон | [`modules/module_template/`](../../modules/module_template/) (`AGENTS.md`, HOWTO, README) |
| Инфра + ops | `modules/<provider>/AGENTS.md` + `README.md` + `.cursor/rules/` |
| Домен + клиент | `modules/<name>/AGENTS.md` + `.cursor/rules/` + `README.md` |

## Связанные правила

| Тема | Файл |
|------|------|
| Когда создавать docs в целом | [`docs.mdc`](../../.cursor/rules/docs.mdc) |
| Пожелания из чата → BEHAVIOR.md | [`module-behavior.mdc`](../../.cursor/rules/module-behavior.mdc) |
| Стиль текста | [`writing-docs-and-rules.mdc`](../../.cursor/rules/writing-docs-and-rules.mdc) |
| Структура модуля | [`modules.mdc`](../../.cursor/rules/modules.mdc) |
| Cursor rules модуля | [`module-cursor-rules.mdc`](../../.cursor/rules/module-cursor-rules.mdc) |
| Карта для людей | [`.docs/modules.md`](../../.docs/modules.md) |
| Вынос модуля в сервис | [`modularization.mdc`](../../.cursor/rules/modularization.mdc) |
