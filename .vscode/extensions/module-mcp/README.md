# ERGO MS Module Cursor MCP

Подхватывает MCP ядра и `modules/*/mcp` в Cursor.

**Основной путь:** `vscode.cursor.mcp.registerServer` — `.cursor/mcp.json` **не перезаписывается**.

**Fallback** (если API Cursor недоступен): запись в `.cursor/mcp.json` **только при реальном изменении** содержимого.

Включённые серверы хранятся в `workspaceState` расширения (не в постоянно обновляемом файле). При первом запуске флаги мигрируют из существующего `mcp.json`.

## Установка

```bash
ergoms install-extensions
```

Reload Window → при доступном Cursor MCP API серверы регистрируются через API; `mcp.json` больше не «сам обновляется» на каждый activate.

## Поведение

| Ситуация | Что происходит |
|----------|----------------|
| Есть Cursor MCP API | `registerServer` для включённых; пути абсолютные, потому что API не задаёт рабочую папку; `mcp.json` не трогаем (кроме однократной очистки серверов ERGO из файла) |
| API нет | Fallback: `mcp.json` пишется только если JSON изменился |
| Watcher (manifest / registry / databases.yaml) | Sync с пропуском, если каталог и список включённых не изменились |
| Activate | Регистрация через API при необходимости; без лишней записи файла |

Включение / выключение:

- **ERGO MS: Enable MCP Servers**
- **ERGO MS: Disable MCP Servers**

## Команды

| Команда | Назначение |
|---------|------------|
| **Sync Module Cursor MCP** | Принудительно обновить каталог и регистрацию |
| **Enable MCP Servers** | Выбрать, какие включить |
| **Disable MCP Servers** | Выбрать, какие выключить |

Лог: Output → **ERGO MS Module MCP**.
