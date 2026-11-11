---
paths:
  - "core/deployment/**"
  - "virtual_env/**"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Артефакты только в корне проекта

Данные ERGO MS лежат внутри корня репозитория. Вне корня — только регистрация служб ОС (Windows SCM, `systemctl link|enable`) и симлинк CLI `/usr/local/bin/ergoms`.

Пути задаёт [`project_layout.py`](../../core/deployment/project_layout.py). Примеры — [`project-root-artifacts-details.mdc`](../../.cursor/rules/project-root-artifacts-details.mdc).

- Кэши, пакеты, TLS, Jupyter, temp — `virtual_env/`
- Env и unit-файлы — `core/deployment/wrappers/`
- Логи — `logs/`; снимки БД — `virtual_env/backups/`; CLI — `core/deployment/bin/`
- Новый путь сначала попадает в `project_layout.py`
- Запрещены `%TEMP%`, `/tmp`, `%ProgramData%`, `/etc` (кроме symlink служб) и apt/dnf-certbot для данных приложения

Исключения, это не данные приложения: NSSM в `virtual_env/packages/nssm`, unit при `systemctl link` остаётся в `wrappers/systemd/`, Docker entrypoint в `/usr/local/lib/ergo-ms`, симлинк `/usr/local/bin/ergoms`.
