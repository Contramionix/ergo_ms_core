---
paths:
  - "core/deployment/windows/**"
  - "core/deployment/linux/**"
  - "**/os_abstraction/**"
  - "**/process-ops.js"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Windows и Linux

Код должен работать на обеих ОС.

Если логика зависит от системы (пути, процессы, shell) — делай абстракцию, не разбрасывай `sys.platform` по бизнес-коду.

Готовые места в проекте:

| Область | Где |
|---------|-----|
| Python | `core/api/src/core/utils/os_abstraction/` |
| Node (процессы) | `core/client/scripts/lib/process-ops.js` |
| Скрипты ergoms | `core/deployment/windows/`, `core/deployment/linux/`, префиксы `win:` / `linux:` в `commands.conf` |
| Системные тесты | `ergoms system-test` на обеих ОС — [`system-test.mdc`](../../.cursor/rules/system-test.mdc); префикс служб `ERGO_SERVICE_PREFIX` |
| `.ps1` с кириллицей | UTF-8 BOM — [`ps1-encoding.mdc`](../../.cursor/rules/ps1-encoding.mdc), `ergoms ps1-encoding-check` |
| `.sh` deployment | LF без BOM — [`sh-encoding.mdc`](../../.cursor/rules/sh-encoding.mdc), `ergoms sh-encoding-check` |

## Связанные правила

| Тема | Файл |
|------|------|
| ergoms, commands.conf | [`ergoms-commands.mdc`](../../.cursor/rules/ergoms-commands.mdc) |
| Lifecycle-pipeline | [`lifecycle-pipeline.mdc`](../../.cursor/rules/lifecycle-pipeline.mdc) |
| UTF-8 BOM в .ps1 | [`ps1-encoding.mdc`](../../.cursor/rules/ps1-encoding.mdc) |
| Системные тесты | [`system-test.mdc`](../../.cursor/rules/system-test.mdc) |
| LF без BOM в .sh | [`sh-encoding.mdc`](../../.cursor/rules/sh-encoding.mdc) |
| Развёртывание | [`core/deployment/logic.md`](../../core/deployment/logic.md) |
| Redis, nginx, TLS | [`deployment-infra.mdc`](../../.cursor/rules/deployment-infra.mdc) |
