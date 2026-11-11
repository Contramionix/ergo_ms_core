---
paths:
  - "core/deployment/**/*.sh"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Shell-скрипты deployment — LF без BOM

На **Linux** bash не запускает `.sh` с **CRLF** или **UTF-8 BOM** в начале файла: shebang и `source` ломаются (`#!/usr/bin/env: No such file or directory`).

На **Windows** правки через Cursor/VS Code часто сохраняют CRLF — Git и проверки должны это отсечь до деплоя.

## Обязательно

- `.sh` в `core/deployment/` — **UTF-8, LF, без BOM**
- Git: [`.gitattributes`](../../.gitattributes) → `core/deployment/**/*.sh text eol=lf`
- Редактор: [`.editorconfig`](../../.editorconfig) → `end_of_line = lf` для `core/deployment/**/*.sh`
- Запись из Python — [`sh_io.write_sh()`](../../core/deployment/scripts/sh_io.py)
- Проверка: `ergoms sh-encoding-check`; исправление: `ergoms sh-encoding-check --fix`
- Входит в `ergoms core-rules-check`
- Перед bash-dispatch на Linux — проверка в [`shell_bridge.py`](../../core/deployment/lifecycle/host/shell_bridge.py)

## Запрещено

```bash
# BAD — CRLF или BOM в ergo_ms.sh / lib/*.sh
#!/usr/bin/env bash
set -euo pipefail
```

```python
# BAD — запись .sh с BOM или platform-newlines
path.write_text(content, encoding='utf-8-sig')
path.write_bytes(b'\xef\xbb\xbf' + content.encode('utf-8'))
```

## Базовый пример

```python
from pathlib import Path
from sh_io import read_sh, write_sh

write_sh(Path('core/deployment/linux/lib/example.sh'), read_sh(path) + '\n# ok\n')
```

## Типичные симптомы

| Симптом на Linux | Причина | Действие |
|---|---|---|
| `line 1: #!/usr/bin/env: No such file or directory` | CRLF и/или BOM | `ergoms sh-encoding-check --fix` |
| Та же ошибка после правки на Windows | checkout с CRLF | pull + `--fix` или `git add --renormalize core/deployment` |

## Связанные правила

| Тема | Файл |
|---|---|
| PowerShell .ps1 (наоборот — **с** BOM) | [`ps1-encoding.mdc`](../../.cursor/rules/ps1-encoding.mdc) |
| Windows и Linux | [`oc.mdc`](../../.cursor/rules/oc.mdc) |
| ergoms, core-rules-check | [`ergoms-commands.mdc`](../../.cursor/rules/ergoms-commands.mdc) |
