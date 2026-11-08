"""
Сборка списка MCP-серверов из ядерного реестра и manifest модулей.

Внутренняя библиотека для расширения ERGO MS Module Cursor MCP
(.vscode/extensions/module-mcp). Пользовательских команд ergoms нет.

Основной путь расширения — vscode.cursor.mcp.registerServer (без постоянной
записи mcp.json). Команда sync здесь — ручной fallback для среды без Cursor API.

  python .cursor/mcp_sync.py list          — текстовый список
  python .cursor/mcp_sync.py list --json   — JSON для расширения
  python .cursor/mcp_sync.py sync          — записать .cursor/mcp.json (только если изменилось)
  python .cursor/mcp_sync.py claude --enable ergo-api ...
                                           — записать .mcp.json для Claude Code этой машины

Claude Code не видит серверы, которые расширение регистрирует через API Cursor.
Ему нужен .mcp.json в корне с абсолютными путями этой машины, поэтому файл
не в git и собирается здесь из того же каталога.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from os_abstraction import get_npx_executable

# Windows: stdout часто cp1252 — русские description в JSON ломают list --json
# (расширение module-mcp тогда получает пустой каталог).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except (AttributeError, OSError, ValueError):
        pass

_CURSOR_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _CURSOR_DIR.parent
REGISTRY_PATH = _CURSOR_DIR / 'mcp.registry.yaml'
MCP_JSON_PATH = _CURSOR_DIR / 'mcp.json'
CLAUDE_MCP_JSON_PATH = PROJECT_ROOT / '.mcp.json'
CLAUDE_DEFAULT_SERVERS = ('ergo-api',)
DATABASES_YAML = PROJECT_ROOT / 'databases.yaml'
MODULES_DIR = PROJECT_ROOT / 'modules'
LAUNCHER = '.cursor/mcp_launcher.js'


def _npx_command() -> str:
    """Путь к npx для Cursor: portable Node, путь относительно корня проекта."""
    found = get_npx_executable()
    if not found:
        return 'npx'
    path = Path(found).resolve()
    try:
        return path.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _section_to_kebab(section: str) -> str:
    """Имя секции databases.yaml → kebab-case для ключа Cursor."""
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', str(section).strip()).strip('-').lower()
    return slug or 'default'


@dataclass
class McpServerEntry:
    name: str
    description: str
    source: str
    script: str
    config: dict[str, Any]


def _load_registry() -> list[dict[str, Any]]:
    if not REGISTRY_PATH.is_file():
        raise SystemExit(f'[ERROR] Не найден реестр: {REGISTRY_PATH}')
    data = yaml.safe_load(REGISTRY_PATH.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise SystemExit('[ERROR] Некорректный формат mcp.registry.yaml')
    servers = data.get('servers')
    if not isinstance(servers, list):
        raise SystemExit('[ERROR] В mcp.registry.yaml ожидается список servers')
    return servers


def _discover_module_manifests() -> list[dict[str, Any]]:
    if not MODULES_DIR.is_dir():
        return []

    discovered: list[dict[str, Any]] = []
    for module_dir in sorted(MODULES_DIR.iterdir()):
        if not module_dir.is_dir() or module_dir.name.startswith('.'):
            continue
        manifest_path = module_dir / 'mcp' / 'manifest.yaml'
        if not manifest_path.is_file():
            continue
        data = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            continue
        server = data.get('server')
        if not isinstance(server, dict):
            print(f'[WARNING] Пропуск {manifest_path}: нет блока server', file=sys.stderr)
            continue
        script_rel = str(server.get('script', '')).strip()
        if not script_rel:
            print(f'[WARNING] Пропуск {manifest_path}: не задан server.script', file=sys.stderr)
            continue
        script_path = module_dir / script_rel
        if not script_path.is_file():
            print(
                f'[WARNING] Пропуск {manifest_path}: файл не найден — {script_path.relative_to(PROJECT_ROOT)}',
                file=sys.stderr,
            )
            continue
        discovered.append({
            'module': data.get('module') or module_dir.name,
            'name': server.get('name', ''),
            'description': server.get('description', ''),
            'script': str(script_path.relative_to(PROJECT_ROOT)).replace('\\', '/'),
            'extra_args': server.get('extra_args') or [],
        })
    return discovered


def _python_entry(
    name: str,
    description: str,
    script_rel: str,
    extra_args: list[Any] | None = None,
    *,
    source: str = 'core',
) -> McpServerEntry:
    script_path = PROJECT_ROOT / script_rel
    if not script_path.is_file():
        raise SystemExit(f'[ERROR] Сервер {name}: файл не найден — {script_rel}')
    args = [LAUNCHER, script_rel.replace('\\', '/')] + list(extra_args or [])
    return McpServerEntry(
        name=name,
        description=description,
        source=source,
        script=script_rel.replace('\\', '/'),
        config={
            'command': 'node',
            'args': args,
        },
    )


def _databases_yaml_entries(item: dict[str, Any]) -> list[McpServerEntry]:
    """Разворачивает type=databases_yaml в одну запись Cursor на секцию databases.yaml."""
    script_rel = str(item.get('script', '')).strip()
    if not script_rel:
        raise SystemExit('[ERROR] type=databases_yaml: нужен script')

    prefix = str(item.get('name', 'ergo-database')).strip() or 'ergo-database'
    sections: dict[str, Any] = {}

    if DATABASES_YAML.is_file():
        try:
            data = yaml.safe_load(DATABASES_YAML.read_text(encoding='utf-8'))
        except Exception as e:
            print(f'[WARNING] Не удалось прочитать databases.yaml: {e}', file=sys.stderr)
            data = None
        if isinstance(data, dict) and isinstance(data.get('databases'), dict):
            sections = data['databases']
        else:
            print(
                '[WARNING] databases.yaml: нет словаря databases — '
                f'будет только {prefix}-default',
                file=sys.stderr,
            )
    else:
        print(
            f'[WARNING] Нет {DATABASES_YAML.name} — будет только {prefix}-default',
            file=sys.stderr,
        )

    if not sections:
        return [
            _python_entry(
                f'{prefix}-default',
                'default — секция из databases.yaml (файл отсутствует или пуст)',
                script_rel,
                ['default'],
            )
        ]

    entries: list[McpServerEntry] = []
    used_names: set[str] = set()
    for section_name, db_config in sections.items():
        kebab = _section_to_kebab(section_name)
        entry_name = f'{prefix}-{kebab}'
        if entry_name in used_names:
            raise SystemExit(
                f'[ERROR] type=databases_yaml: дублирующееся имя MCP после нормализации: {entry_name}'
            )
        used_names.add(entry_name)

        engine = 'postgresql'
        if isinstance(db_config, dict):
            engine = str(db_config.get('engine', 'postgresql')).strip().lower() or 'postgresql'

        description = f'{engine} — секция {section_name} из databases.yaml'
        entries.append(
            _python_entry(entry_name, description, script_rel, [str(section_name)])
        )
    return entries


def _registry_to_entries(item: dict[str, Any]) -> list[McpServerEntry]:
    name = str(item.get('name', '')).strip()
    if not name:
        raise SystemExit('[ERROR] В реестре сервер без name')

    description = str(item.get('description', '')).strip()
    server_type = str(item.get('type', 'python')).strip().lower()

    if server_type == 'databases_yaml':
        return _databases_yaml_entries(item)

    if server_type == 'npx':
        package = str(item.get('package', '')).strip()
        if not package:
            raise SystemExit(f'[ERROR] Сервер {name}: для type=npx нужен package')
        args = ['-y', package] + list(item.get('args') or [])
        npx_command = _npx_command()
        return [
            McpServerEntry(
                name=name,
                description=description,
                source='core',
                script=f'{npx_command} {package}',
                config={
                    'command': npx_command,
                    'args': args,
                },
            )
        ]

    if server_type == 'python':
        script_rel = str(item.get('script', '')).strip()
        if not script_rel:
            raise SystemExit(f'[ERROR] Сервер {name}: для type=python нужен script')
        return [
            _python_entry(
                name,
                description,
                script_rel,
                list(item.get('extra_args') or []),
            )
        ]

    raise SystemExit(f'[ERROR] Сервер {name}: неизвестный type={server_type}')


def _module_to_entry(item: dict[str, Any]) -> McpServerEntry:
    name = str(item.get('name', '')).strip()
    if not name:
        raise SystemExit('[ERROR] В manifest модуля не задан server.name')

    module = str(item.get('module', '')).strip()
    script = str(item.get('script', '')).replace('\\', '/')
    extra_args = list(item.get('extra_args') or [])

    return McpServerEntry(
        name=name,
        description=str(item.get('description', '')).strip(),
        source=f'module:{module}' if module else 'module',
        script=script,
        config={
            'command': 'node',
            'args': [LAUNCHER, script] + extra_args,
        },
    )


def collect_entries() -> list[McpServerEntry]:
    entries: list[McpServerEntry] = []

    for item in _load_registry():
        entries.extend(_registry_to_entries(item))

    for item in _discover_module_manifests():
        entries.append(_module_to_entry(item))

    names = [e.name for e in entries]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise SystemExit(f'[ERROR] Дублирующиеся имена MCP: {", ".join(sorted(duplicates))}')

    return entries


def build_mcp_json(
    entries: list[McpServerEntry],
    *,
    disabled_by_default: bool = True,
) -> dict[str, Any]:
    """Собирает mcp.json. По умолчанию каждый сервер с disabled: true (установлен, выключен)."""
    existing: dict[str, Any] = {}
    if MCP_JSON_PATH.is_file():
        try:
            data = json.loads(MCP_JSON_PATH.read_text(encoding='utf-8'))
            if isinstance(data, dict) and isinstance(data.get('mcpServers'), dict):
                existing = data['mcpServers']
        except Exception:
            existing = {}

    servers: dict[str, Any] = {}
    for entry in sorted(entries, key=lambda e: e.name):
        prev = existing.get(entry.name)
        if isinstance(prev, dict) and isinstance(prev.get('disabled'), bool):
            disabled = prev['disabled']
        else:
            disabled = disabled_by_default
        servers[entry.name] = {
            **entry.config,
            'disabled': disabled,
        }
    return {'mcpServers': servers}


def entries_as_jsonable(entries: list[McpServerEntry]) -> list[dict[str, Any]]:
    return [asdict(e) for e in sorted(entries, key=lambda e: e.name)]


def cmd_list(*, as_json: bool = False) -> int:
    entries = collect_entries()
    if as_json:
        print(json.dumps(entries_as_jsonable(entries), ensure_ascii=False))
        return 0

    if not entries:
        print('[INFO] MCP-серверы не найдены')
        return 0

    print(f'{"Name":<36} {"Source":<24} Script / package')
    print('-' * 90)
    for entry in entries:
        print(f'{entry.name:<36} {entry.source:<24} {entry.script}')
    print(f'\n[INFO] Всего: {len(entries)}. Регистрация — расширение Module Cursor MCP')
    return 0


def cmd_sync() -> int:
    """Fallback: записывает mcp.json только если содержимое изменилось (merge сохраняет disabled)."""
    entries = collect_entries()
    payload = build_mcp_json(entries, disabled_by_default=True)
    next_text = json.dumps(payload, ensure_ascii=False, indent=4) + '\n'
    if MCP_JSON_PATH.is_file() and MCP_JSON_PATH.read_text(encoding='utf-8') == next_text:
        total = len(payload['mcpServers'])
        print(
            f'[SKIP] {MCP_JSON_PATH.relative_to(PROJECT_ROOT)} без изменений '
            f'({total} серверов)'
        )
        print('[INFO] Основной путь — расширение Module Cursor MCP (registerServer)')
        return 0

    MCP_JSON_PATH.write_text(next_text, encoding='utf-8')
    enabled = sum(1 for s in payload['mcpServers'].values() if s.get('disabled') is False)
    total = len(payload['mcpServers'])
    print(
        f'[OK] Записан {MCP_JSON_PATH.relative_to(PROJECT_ROOT)} '
        f'({total} установлено, {enabled} включено, {total - enabled} выключено)'
    )
    print(
        '[INFO] Это fallback без Cursor API. Обычно регистрация — расширение Module Cursor MCP'
    )
    return 0


def _portable_node() -> str:
    base = PROJECT_ROOT / 'virtual_env' / 'packages' / 'nodejs'
    candidate = base / 'node.exe' if sys.platform == 'win32' else base / 'bin' / 'node'
    return candidate.as_posix() if candidate.is_file() else 'node'


def _absolute_arg(arg: Any) -> Any:
    """Относительный путь внутри проекта → абсолютный: Claude Code не обязан стартовать из корня."""
    if not isinstance(arg, str) or arg.startswith('-') or '/' not in arg:
        return arg
    candidate = PROJECT_ROOT / arg
    return candidate.resolve().as_posix() if candidate.exists() else arg


def _claude_server(entry: McpServerEntry) -> dict[str, Any]:
    command = str(entry.config.get('command', ''))
    args = [_absolute_arg(arg) for arg in entry.config.get('args') or []]
    if command in ('node', 'node.exe'):
        command = _portable_node()
    else:
        command = _absolute_arg(command)
        # .cmd на Windows без оболочки не стартует.
        if sys.platform == 'win32' and command.lower().endswith('.cmd'):
            args = ['/c', command, *args]
            command = 'cmd'
    env = {'PYTHONIOENCODING': 'utf-8'}
    node = _portable_node()
    if node != 'node':
        # Обёртки зовут npx, а тот — node: portable Node впереди PATH, как у расширения Cursor.
        separator = ';' if sys.platform == 'win32' else ':'
        env['PATH'] = f'{Path(node).parent.as_posix()}{separator}${{PATH}}'
    return {
        'type': 'stdio',
        'command': command,
        'args': args,
        'env': env,
    }


def _claude_enabled_now() -> list[str]:
    if not CLAUDE_MCP_JSON_PATH.is_file():
        return []
    try:
        data = json.loads(CLAUDE_MCP_JSON_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    servers = data.get('mcpServers') if isinstance(data, dict) else None
    return list(servers) if isinstance(servers, dict) else []


def cmd_claude(enable: list[str] | None) -> int:
    """Записывает .mcp.json для Claude Code. Без --enable берёт серверы, уже лежащие в файле."""
    entries = {entry.name: entry for entry in collect_entries()}
    wanted = enable or _claude_enabled_now() or list(CLAUDE_DEFAULT_SERVERS)
    unknown = [name for name in wanted if name not in entries]
    if unknown:
        print(f'[ERROR] Нет в каталоге: {", ".join(unknown)}. Доступны: {", ".join(sorted(entries))}')
        return 1
    payload = {'mcpServers': {name: _claude_server(entries[name]) for name in sorted(set(wanted))}}
    next_text = json.dumps(payload, ensure_ascii=False, indent=2) + '\n'
    rel = CLAUDE_MCP_JSON_PATH.relative_to(PROJECT_ROOT)
    if CLAUDE_MCP_JSON_PATH.is_file() and CLAUDE_MCP_JSON_PATH.read_text(encoding='utf-8') == next_text:
        print(f'[SKIP] {rel} без изменений: {", ".join(payload["mcpServers"])}')
        return 0
    CLAUDE_MCP_JSON_PATH.write_text(next_text, encoding='utf-8')
    print(f'[OK] Записан {rel}: {", ".join(payload["mcpServers"])}')
    print('[INFO] Перезапустите сессию Claude Code и разрешите серверы проекта')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Внутренняя сборка MCP для расширения module-mcp (не ergoms)',
    )
    sub = parser.add_subparsers(dest='command', required=True)
    list_parser = sub.add_parser('list', help='Список всех MCP-серверов')
    list_parser.add_argument(
        '--json',
        action='store_true',
        help='Вывести JSON-массив для расширения',
    )
    sub.add_parser('sync', help='Записать .cursor/mcp.json (fallback расширения)')
    claude_parser = sub.add_parser('claude', help='Записать .mcp.json для Claude Code этой машины')
    claude_parser.add_argument(
        '--enable',
        nargs='+',
        metavar='NAME',
        help='Имена серверов из list; без флага остаются серверы из текущего .mcp.json',
    )
    args = parser.parse_args()

    if args.command == 'list':
        return cmd_list(as_json=bool(getattr(args, 'json', False)))
    if args.command == 'sync':
        return cmd_sync()
    if args.command == 'claude':
        return cmd_claude(args.enable)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
