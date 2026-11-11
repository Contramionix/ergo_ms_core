# ERGO MS Module Cursor Rules

Правила модуля лежат в `modules/<имя>/.cursor/rules/*.mdc`. Cursor читает вложенные `.cursor/rules` сам.

Раньше расширение копировало те же файлы в `virtual_env/cache/cursor-module-plugins/` и регистрировало их через `vscode.cursor.plugins.addPlugin`. Из-за этого каждое правило модуля попадало в контекст дважды. Регистрация копий отключена.

При запуске расширение снимает уже зарегистрированные копии и удаляет staging. Команда **ERGO MS: Убрать копии правил модулей** делает то же по запросу. Лог — Output → **ERGO MS Module Rules**.

MCP — отдельное расширение `module-mcp`.

## Конвенция в модуле

```text
modules/<имя>/
  .cursor/rules/
    <topic>.mdc
  AGENTS.md
```

```yaml
---
description: <имя> — тема
globs:
  - "modules/<имя>/**"
alwaysApply: false
---
```

Не ставьте `alwaysApply: true` на модульных правилах.
