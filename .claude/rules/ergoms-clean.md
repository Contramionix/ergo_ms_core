---
paths:
  - "core/deployment/**/clean.ps1"
  - "core/deployment/**/clean.sh"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Остановка portable-инфраструктуры в `ergoms clean`

Перед очисткой `virtual_env/packages` (и при ошибке «не удалось удалить: nginx, redis») процессы и службы portable nginx / Redis / PostgreSQL **обязаны** быть остановлены. Иначе Windows держит файлы занятыми, и шаг clean завершается с `[ERROR]`.

Эталон: [`Stop-BlockingProcessesForClean`](../../core/deployment/windows/lib/clean.ps1), [`stop_blocking_processes_for_clean`](../../core/deployment/linux/lib/clean.sh).

## Кратко

- Все OS-службы проекта — **`ergo_ms_*`** (API, Celery, nginx, Redis, Postgres).
- При clean также останавливай legacy `ergo-*` (старые имена до унификации префикса).
- Процессы могут работать **без** службы (dev / foreground). Их exe — под `virtual_env/packages/{nginx,redis,postgres}/`.
- Сначала останови службы (NSSM иначе перезапустит процесс), затем заверши процессы из `packages`.
- Не полагайся только на остановку `virtual_env/python` и `node` — они packages не освобождают.

## Обязательно

| Что | Как |
|-----|-----|
| Правка clean | Сохрани остановку `ergo_ms_*` (+ legacy `ergo-*`) и процессов с путём/`CommandLine` в `virtual_env/packages` |
| Linux | Вызови `nginx_stop_service` / `redis_stop` / `postgres_stop` (quiet), затем systemctl/`fuser`/`pkill` по packages |
| Новый portable в packages | Добавь его в ту же остановку clean (служба + path match), иначе `ergoms clean` снова упрётся в блокировку файлов |

## Запрещено

```powershell
# BAD — без ergo_ms_* и без packages
Get-Service -Name 'ergo-*' | Stop-Service -Force
# nginx/redis продолжают держать virtual_env/packages
```

```bash
# BAD — только venv, packages не трогаем
pkill -f "$root/virtual_env/python"
# portable nginx/redis остаются запущенными
```

## Симптом

```
[ERROR] Не удалось очистить virtual_env/packages: не удалось удалить: nginx, redis
  Закройте терминалы… и снова выполните ergoms clean
```

Причина почти всегда: живые `nginx.exe` / `redis-server.exe` (или служба `ergo_ms_*`). Исправляй остановку в clean, не предлагай вручную «убейте nginx» как основной путь.

## Связанные правила

| Тема | Файл |
|---|---|
| packages, пути | [`project-root-artifacts.mdc`](../../.cursor/rules/project-root-artifacts.mdc) |
| Redis, nginx | [`deployment-infra.mdc`](../../.cursor/rules/deployment-infra.mdc) |
| Portable PostgreSQL | [`postgres-portable.mdc`](../../.cursor/rules/postgres-portable.mdc) |
| Метки консоли clean | [`console-output.mdc`](../../.cursor/rules/console-output.mdc) |
| Команды ergoms | [`no-direct-manage-py.mdc`](../../.cursor/rules/no-direct-manage-py.mdc) |
