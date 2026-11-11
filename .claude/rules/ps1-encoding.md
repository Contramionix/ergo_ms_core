---
paths:
  - "core/deployment/**/*.ps1"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Кодировка PowerShell-скриптов (Windows)

Встроенный **Windows PowerShell 5.1** (VS Code tasks, `ergo_ms.ps1`) читает `.ps1` **без BOM** в системной кодировке (часто CP1251). Кириллица в строках ломает разбор: `ParserError`, «missing terminator», ложная `}` в конце файла.

PowerShell 7+ BOM не требует; в ERGO MS ориентир — **PS 5.1** и задачи `.vscode/tasks.json`.

## Кратко

- `.ps1` с **не-ASCII** (кириллица в сообщениях пользователю) — **UTF-8 с BOM**
- Запись из Python — только [`ps1_io.write_ps1()`](../../core/deployment/scripts/ps1_io.py)
- Проверка: `ergoms ps1-encoding-check`; исправление: `ergoms ps1-encoding-check --fix`
- Входит в `ergoms core-rules-check`
- Перед `internal_dispatch.ps1` — проверка BOM в [`shell_bridge.py`](../../core/deployment/lifecycle/host/shell_bridge.py)

## Обязательно

```python
from ps1_io import read_ps1, write_ps1

content = read_ps1(path)
write_ps1(path, content)  # UTF-8 + BOM
```

Редактор / агент: сохранять **UTF-8 with BOM** для любого нового или изменённого `.ps1` в `core/deployment/` с русским текстом.

## Запрещено

```python
# BAD — без BOM
path.write_text(ps1_content, encoding='utf-8')
```

```powershell
# BAD — кириллица в .ps1, сохранённом как UTF-8 no BOM на диске для PS 5.1
throw "Неизвестная категория: $Category"
```

Метки `[OK]` / `[ERROR]` — только английские ([`console-output.mdc`](../../.cursor/rules/console-output.mdc)); русский — в тексте сообщения после метки.

## Типичный симптом

| Симптом | Причина | Действие |
|---------|---------|----------|
| `ÐÐµÐ¸Ð·Ð²ÐµÑÑ‚Ð½Ð°Ñ` в ошибке PS | UTF-8 прочитан как CP1251 | `ergoms ps1-encoding-check --fix` |
| `The string is missing the terminator` | то же | BOM + перезапуск команды |

## Связанные правила

| Тема | Файл |
|------|------|
| Lifecycle, internal_dispatch | [`lifecycle-pipeline.mdc`](../../.cursor/rules/lifecycle-pipeline.mdc) |
| Консоль ergoms | [`console-output.mdc`](../../.cursor/rules/console-output.mdc) |
| Windows / Linux | [`oc.mdc`](../../.cursor/rules/oc.mdc) |
| Тесты deployment | [`core/deployment/windows/lib/test/README.md`](../../core/deployment/windows/lib/test/README.md) |
