"""
Обертка для запуска MCP-сервера БД по секции databases.yaml.

По полю engine выбирается npx-пакет (postgresql / mysql / mssql / sqlite).
Имя секции — первый аргумент (по умолчанию default).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

_cursor_dir = Path(__file__).parent.resolve()
if str(_cursor_dir) not in sys.path:
    sys.path.insert(0, str(_cursor_dir))
from os_abstraction import get_npx_executable

PROJECT_DIR = Path(__file__).parent.parent.resolve()
DATABASES_YAML = PROJECT_DIR / 'databases.yaml'

POSTGRES_PACKAGE = '@modelcontextprotocol/server-postgres'
MULTI_DB_PACKAGE = '@executeautomation/database-server'

SUPPORTED_ENGINES = frozenset({'postgresql', 'mysql', 'mssql', 'sqlite'})


def _fail(message: str) -> None:
    print(f'ОШИБКА: {message}', file=sys.stderr)
    sys.exit(1)


def load_section(db_name: str) -> dict[str, Any]:
    if not DATABASES_YAML.is_file():
        _fail(f'файл databases.yaml не найден: {DATABASES_YAML}')

    try:
        with open(DATABASES_YAML, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        _fail(f'не удалось прочитать databases.yaml: {e}')

    if not config or 'databases' not in config:
        _fail('неверный формат файла databases.yaml')

    databases = config['databases']
    if not isinstance(databases, dict):
        _fail('в databases.yaml ожидается словарь databases')

    db_config = databases.get(db_name)
    if not isinstance(db_config, dict):
        _fail(f"конфигурация для БД '{db_name}' не найдена")

    return db_config


def _require_fields(db_config: dict[str, Any], *fields: str) -> None:
    missing = [f for f in fields if not db_config.get(f) and db_config.get(f) != 0]
    if missing:
        _fail(f"в секции БД не заданы поля: {', '.join(missing)}")


def build_npx_args(db_config: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    """Аргументы npx и добавка к окружению процесса.

    Пароль PostgreSQL идёт через PGPASSWORD, а не в адресе: аргументы процесса
    печатают npm и сообщение об ошибке, а stderr MCP оседает в логах Cursor и Claude Code.
    """
    engine = str(db_config.get('engine', 'postgresql')).strip().lower()
    if engine not in SUPPORTED_ENGINES:
        _fail(
            f"неподдерживаемый engine '{engine}'. "
            f"Допустимо: {', '.join(sorted(SUPPORTED_ENGINES))}"
        )

    if engine == 'postgresql':
        _require_fields(db_config, 'user', 'password', 'host', 'name')
        port = db_config.get('port', 5432)
        user = quote(str(db_config['user']), safe='')
        host = db_config['host']
        name = db_config['name']
        # Драйвер pg берёт пароль из PGPASSWORD, когда в адресе его нет.
        uri = f'postgresql://{user}@{host}:{port}/{name}'
        return ['-y', POSTGRES_PACKAGE, uri], {'PGPASSWORD': str(db_config['password'])}

    if engine == 'sqlite':
        _require_fields(db_config, 'name')
        db_path = Path(str(db_config['name']))
        if not db_path.is_absolute():
            db_path = (PROJECT_DIR / db_path).resolve()
        return ['-y', MULTI_DB_PACKAGE, str(db_path)], {}

    if engine == 'mysql':
        _require_fields(db_config, 'user', 'password', 'host', 'name')
        port = str(db_config.get('port', 3306))
        return [
            '-y',
            MULTI_DB_PACKAGE,
            '--mysql',
            '--host', str(db_config['host']),
            '--port', port,
            '--database', str(db_config['name']),
            '--user', str(db_config['user']),
            '--password', str(db_config['password']),
        ], {}

    # mssql
    _require_fields(db_config, 'user', 'password', 'host', 'name')
    port = str(db_config.get('port', 1433))
    return [
        '-y',
        MULTI_DB_PACKAGE,
        '--sqlserver',
        '--server', str(db_config['host']),
        '--port', port,
        '--database', str(db_config['name']),
        '--user', str(db_config['user']),
        '--password', str(db_config['password']),
    ], {}


def main() -> None:
    db_name = sys.argv[1] if len(sys.argv) > 1 else 'default'
    db_config = load_section(db_name)
    package_args, extra_env = build_npx_args(db_config)

    npx_executable = get_npx_executable()
    if not npx_executable:
        _fail('npx не найден в PATH. Установите Node.js и перезапустите терминал.')

    try:
        subprocess.run([npx_executable, *package_args], check=True, env={**os.environ, **extra_env})
    except subprocess.CalledProcessError as e:
        # Текст исключения повторяет аргументы, а у MySQL и MSSQL там пароль.
        print(f'ОШИБКА при запуске MCP сервера: код выхода {e.returncode}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nMCP сервер остановлен', file=sys.stderr)
        sys.exit(0)


if __name__ == '__main__':
    main()
