---
paths:
  - "modules/**/ergoms.conf"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Справка ergoms в модулях

Команды модуля описываются в **`modules/<имя>/ergoms.conf`**, справка для пользователя — в **`modules/<имя>/ergoms.help.yaml`**. Ядро не хранит описания модульных команд.

## Кратко

- Вызов: `ergoms <имя_модуля>:<команда> [аргументы]`
- Оглавление модулей: `ergoms help modules`
- Справка по модулю: `ergoms help module <имя>`
- Текст справки — **русские plain-строки в источнике** `ergoms.help.yaml`; переводы — overlay `modules/<имя>/locales/<lang>/ergoms.help.yaml` (та же структура, deep-merge). Имена команд и путей — как в коде

## Обязательно

При добавлении или изменении строки в `ergoms.conf`:

1. Создай или обнови **`ergoms.help.yaml`** в корне модуля (русский source).
2. Для каждой команды conf добавь `commands.<имя>.summary` на русском.
3. Переводы — в `modules/<имя>/locales/<lang>/ergoms.help.yaml` (например `en`, `fr`).
4. Поле `module` в yaml совпадает с именем каталога (`kebab-case`).
5. Эталон — `modules/<name>/ergoms.help.yaml` рядом с `ergoms.conf`.

## Формат ergoms.help.yaml (source, ru)

```yaml
module: <name>
title: "Мой модуль"
summary: "Кратко о назначении модуля"

commands:
  install:
    summary: "Установить все зависимости модуля"

notes:
  - "Вызов: ergoms <name>:<команда>"
```

Перевод (overlay, та же структура):

```yaml
# modules/<name>/locales/en/ergoms.help.yaml
title: "My module"
summary: "Brief module description"
commands:
  install:
    summary: "Install all module dependencies"
```

| Поле | Назначение |
|------|------------|
| `module` | Имя каталога модуля |
| `title` | Заголовок в `ergoms help module` |
| `summary` | Одна строка для `ergoms help modules` |
| `commands.<имя>.summary` | Описание команды (ключ = имя в ergoms.conf без префикса) |
| `notes` | Дополнительные примечания (необязательно) |

## Запрещено

- Описания модульных ergoms-команд в `core/deployment/help.manifest.yaml` или в `ergoms_help.py`
- Вложенные карты языков в одном файле (`title: { ru: …, en: … }`) — только source + overlay
- Команда в conf без `summary` в help (при `help module` будет предупреждение)

## Где смотреть

| Что | Файл |
|-----|------|
| Рендер справки | [`core/deployment/scripts/ergoms_help.py`](../../core/deployment/scripts/ergoms_help.py) |
| Справка ядра | [`core/deployment/help.manifest.yaml`](../../core/deployment/help.manifest.yaml) + overlays `locales/<lang>/help.manifest.yaml` |
| Локализация CLI | [`cli_locale.py`](../../core/deployment/cli_locale.py) |
| Эталон модуля | `modules/<name>/ergoms.help.yaml` |

## Связанные правила

| Тема | Файл |
|------|------|
| Структура модулей | [`modules.mdc`](../../.cursor/rules/modules.mdc) |
| Команды ergoms | [`ergoms-commands.mdc`](../../.cursor/rules/ergoms-commands.mdc) |
| Стиль текста | [`writing-docs-and-rules.mdc`](../../.cursor/rules/writing-docs-and-rules.mdc) |
