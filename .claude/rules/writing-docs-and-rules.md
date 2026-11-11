---
paths:
  - ".cursor/rules/**"
  - "modules/*/.cursor/rules/**"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Стиль правил Cursor

Как писать `.cursor/rules/*.mdc` и корневой [`.cursorrules`](../../.cursorrules). Документация для людей — [`docs-prose.mdc`](../../.cursor/rules/docs-prose.mdc). Когда создавать документы — [`docs.mdc`](../../.cursor/rules/docs.mdc).

## Для агента

1. Одна тема — один раздел. Заголовок `##` сам отвечает, о чём блок.
2. Сначала суть, потом детали. Явные глаголы: «Используй», «Запрещено», «Проверь».
3. Один термин — одно значение. Раздел можно вырезать в контекст, и он остаётся понятным.
4. `description` — одно предложение с существительными из реальных задач (`SelectBox`, `migrate`, `ModuleBridge`).

Язык — русский. Английский только в именах кода, командах и устоявшихся названиях (Django, Vue, PostgreSQL, ergoms). Части приложения — **сервер** и **клиент**.

## Файл и frontmatter

```yaml
---
description: Одна строка — тема и ключевые сущности
globs:
  - "**/*.py"
  - core/api/**/*.py
alwaysApply: false
---
```

| Поле | Когда |
|---|-----|
| `alwaysApply: true` | Только то, без чего агент ломает проект в любой задаче: isolation, ergoms, `virtual_env`, краткий security, краткая архитектура, куда коммитить, `docs` / `code` / `clarifying-questions`, тон чата. Без `globs` |
| `globs` | YAML-список. Не CSV в кавычках, не `{a,b}` / `*.{vue,js}` |
| только `description` | Правило по запросу: агент подтягивает по ключевым словам |

### Лимиты размера

| Что | Потолок |
|---|---|
| Сумма файлов с `alwaysApply: true` в корневом `.cursor/rules/` | 20 КБ |
| Одно правило с glob на весь модуль (`modules/<name>/**`) | 10 КБ |
| `BEHAVIOR.md` одним файлом, без `behavior/` | 15 КБ |
| Одно правило | около 300 строк, дальше дели по теме |

Длинные детали — в правиле по запросу или с узким glob, из краткого правила только ссылка. Эталон: [`security.mdc`](../../.cursor/rules/security.mdc) → [`security-details.mdc`](../../.cursor/rules/security-details.mdc).

Проверка: `ergoms core-rules-check`.

## Тело правила

1. `# Заголовок`
2. **Кратко** — 3–7 пунктов
3. **Обязательно** / **Запрещено**
4. Один короткий пример «плохо / хорошо» или эталон с путём
5. Таблица ссылок, если без неё не найти соседнее правило

Имена установленных модулей в правилах ядра — только `<name>` и `modules/<name>/`. Исключение: `globs` и тело правила, которое само привязано к модулю.

## Правила модуля

```text
modules/<name>/.cursor/rules/<topic>.mdc
modules/<name>/AGENTS.md
modules/<name>/BEHAVIOR.md
```

Cursor читает вложенные `.cursor/rules` сам. Копию через plugins API не регистрируй. Подробности: [`module-cursor-rules.mdc`](../../.cursor/rules/module-cursor-rules.mdc).

`alwaysApply: true` на модульном правиле запрещён. Нормы из чата — [`module-behavior.mdc`](../../.cursor/rules/module-behavior.mdc): оглавление `BEHAVIOR.md`, текст темы в `behavior/<тема>.md`.

## Корневой `.cursorrules`

Кнопка **Generate commit message** читает только [`.cursorrules`](../../.cursorrules) в корне обёртки, не User Rules и не `.mdc`. Файл обязателен в git. Туда же не копируй полный текст в `.mdc` и не удаляй файл как устаревший.

Текст: русский, `<type>: <описание>` без scope, 1–3 предложения, `feat` только для новой возможности. Куда класть коммит — [`git-commits.mdc`](../../.cursor/rules/git-commits.mdc). Тон чата — [`chat-style.mdc`](../../.cursor/rules/chat-style.mdc).

## Чеклист `.mdc`

- [ ] `description` отражает тему
- [ ] `alwaysApply: true` только для неснимаемого минимума и без `globs`
- [ ] `globs` — YAML-список, без `**/*.md` на всё подряд
- [ ] Размер в лимитах выше
- [ ] Нет дубля другого правила — есть ссылка
- [ ] Стиль коммитов — только в `.cursorrules`
