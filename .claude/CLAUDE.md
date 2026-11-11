# ergo_ms — инструкции для Claude Code

Правила из `.cursor/rules` лежат в `.claude/rules/` и собираются автоматически. Для alwaysApply-правил копии без `paths` грузятся в каждой сессии, остальные — при работе с подходящими файлами.

Правила модулей `modules/<имя>/.cursor/rules/*.mdc` копируются в `.claude/rules/modules/<имя>/` и грузятся по `globs` модуля. Этот каталог не в git: его пересобирает хук SessionStart из `.claude/settings.json`. Вложенный `modules/<имя>/.claude/rules/` Claude Code не читает, туда правила не клади.

Правила без `globs` и `alwaysApply` Cursor подключает по описанию. Для них есть оглавления: `.claude/rules/rules-index.md` (ядро), `.claude/rules/modules/rules-index.md` (модули) и `.claude/rules/local/rules-index.md` (личные `*.local.mdc` этого сервера, не в git). Если задача совпадает с описанием в оглавлении, сначала открой это правило, потом действуй. Доступ к узлам кластера, SSH и VPN описаны в локальных правилах.

Менять правила нужно в `.cursor/rules` (корня или модуля), копии не редактировать. После правок запустить `python3 .claude/scripts/sync_claude_rules.py`.
