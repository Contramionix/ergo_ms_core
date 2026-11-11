"""Цель команды ядра: файл, рецепт или команда Django должны существовать.

Модуль на стандартной библиотеке, чтобы unit-тест не поднимал Django.
"""

from __future__ import annotations

import re
from pathlib import Path

from command_conf import (
    LINUX_ONLY_WRAPPER_COMMANDS,
    PROXY_WRAPPER_COMMANDS,
    SHARED_WRAPPER_COMMANDS,
    load_commands_conf,
    missing_platform_arms,
    split_composite_command,
)

# Совпадает с commands.discovery.DJANGO_BUILTIN_COMMANDS. Копия здесь, чтобы
# проверка commands.conf не импортировала пакет commands и Poetry.
DJANGO_BUILTIN_COMMANDS = frozenset({
    'changepassword', 'check', 'clearsessions', 'collectstatic', 'compilemessages',
    'createcachetable', 'createsuperuser', 'dbshell', 'diffsettings', 'dumpdata',
    'flush', 'inspectdb', 'loaddata', 'makemessages', 'makemigrations', 'migrate',
    'runserver', 'sendtestemail', 'shell', 'showmigrations', 'sqlflush', 'sqlmigrate',
    'sqlsequencereset', 'squashmigrations', 'startapp', 'startproject', 'test', 'testserver',
})

_HELP_NAME = re.compile(r'^\s+- name: ([a-zA-Z0-9_-]+)\s*$', re.M)
_SCRIPT_PATH = re.compile(
    r'(?:core[/\\][\w./\\-]+|\.vscode[/\\][\w./\\-]+)\.(?:py|js|ps1|sh)',
)
_GENERIC_NO_FILE = frozenset({'poetry', 'npm', 'shell', 'media_api', 'win', 'linux'})


def help_command_names(text: str) -> set[str]:
    return set(_HELP_NAME.findall(text))


def django_management_commands(api_root: Path) -> set[str]:
    names: set[str] = set()
    if not api_root.is_dir():
        return names
    for path in api_root.rglob('management/commands/*.py'):
        if path.name == '__init__.py' or path.name.startswith('_'):
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        if 'class Command' in text:
            names.add(path.stem)
    return names


def _normalize_script(match: str) -> str:
    return match.replace('\\', '/')


def collect_command_problems(
    root: Path,
    *,
    recipes: set[str],
    conf: dict[str, str] | None = None,
    help_text: str | None = None,
) -> list[str]:
    """Пустой список — справка резолвится, цель commands.conf существует."""
    deployment = root / 'core' / 'deployment'
    if conf is None:
        conf = load_commands_conf(deployment / 'commands.conf')
    if help_text is None:
        help_text = (deployment / 'help.manifest.yaml').read_text(encoding='utf-8')

    problems: list[str] = []
    known = set(conf) | SHARED_WRAPPER_COMMANDS | LINUX_ONLY_WRAPPER_COMMANDS | PROXY_WRAPPER_COMMANDS
    for name in sorted(help_command_names(help_text) - known):
        problems.append(f'help:{name}: нет в commands.conf и во встроенных командах')

    for name in sorted(set(conf) - help_command_names(help_text)):
        problems.append(f'conf:{name}: нет строки в help.manifest.yaml')

    api_commands = django_management_commands(root / 'core' / 'api') | DJANGO_BUILTIN_COMMANDS
    for name, body in conf.items():
        absent = missing_platform_arms(body)
        if absent:
            problems.append(f'{name}: нет ветки {", ".join(sorted(absent))}')
        for step in split_composite_command(body):
            problems.extend(_step_problems(root, name, step, recipes, api_commands))
    return problems


def _step_problems(
    root: Path,
    name: str,
    step: str,
    recipes: set[str],
    api_commands: set[str],
) -> list[str]:
    problems: list[str] = []
    prefix = ''
    payload = step.strip()
    if ':' in step:
        head, tail = step.split(':', 1)
        head = head.strip()
        if head in _GENERIC_NO_FILE or head == 'lifecycle' or head == 'api':
            prefix = head
            payload = tail.strip()

    if prefix == 'lifecycle':
        recipe = payload.split()[0] if payload else ''
        if recipe not in recipes:
            problems.append(f'{name}: нет рецепта {recipe}')
    elif prefix == 'api':
        command = payload.split()[0] if payload else ''
        if command not in api_commands:
            problems.append(f'{name}: нет команды Django {command}')

    for match in _SCRIPT_PATH.findall(step):
        rel = _normalize_script(match)
        if not (root / rel).is_file():
            problems.append(f'{name}: нет файла {rel}')
    return problems
