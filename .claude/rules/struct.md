<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Архитектура ERGO MS

Сервер — Django (`core/api/`), клиент — Vue (`core/client/`). Ядро: `api/`, `client/`, `media_api/` и `deployment/`. Модули — `modules/<имя>/` (submodule). Community-тексты — `core/.github`. После clone: `git submodule update --init --recursive`.

Связь модуль↔модуль и ядро↔домен модуля — только ModuleBridge и hook-файлы с фиксированным именем. Каталог — [`modules.mdc`](../../.cursor/rules/modules.mdc). Вынос процесса — [`modularization.mdc`](../../.cursor/rules/modularization.mdc). Режимы — корневой `.env`, детали — [`env-examples.mdc`](../../.cursor/rules/env-examples.mdc).

В ядре запрещены `from modules.<имя>.api...`, имена установленных модулей даже в комментариях, static import страниц модуля и обход моста. Проверка — `ergoms core-rules-check`. Изоляция подробнее — [`core-module-isolation.mdc`](../../.cursor/rules/core-module-isolation.mdc).
