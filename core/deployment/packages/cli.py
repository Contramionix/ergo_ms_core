"""
CLI portable-пакетов.

Вызов:
  python core/deployment/packages/cli.py list
  python core/deployment/packages/cli.py status [name]
  python core/deployment/packages/cli.py install <name> [--force] [--refresh]
  python core/deployment/packages/cli.py uninstall <name> [--purge-extra]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PACKAGES_PKG_DIR = Path(__file__).resolve().parent
_DEPLOYMENT_DIR = _PACKAGES_PKG_DIR.parent
_PROJECT_ROOT = _DEPLOYMENT_DIR.parent.parent
if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))

from console_tags import configure_stdio_utf8, format_console  # noqa: E402
from packages.installer import (  # noqa: E402
    install_package,
    list_statuses,
    status_for,
    uninstall_package,
)
from packages.registry import PackageRegistryError, get_package  # noqa: E402
from runtime_requirements import RuntimeRequirementsError  # noqa: E402
from runtime_requirements.plan import install_required_tools, resolve_plan  # noqa: E402


def _resolve_root(raw: Path | None) -> Path:
    root = (raw or _PROJECT_ROOT).resolve()
    if not (root / 'pyproject.toml').is_file():
        raise SystemExit(format_console('error', f'Корень проекта не найден: {root}'))
    return root


def cmd_list(root: Path) -> int:
    try:
        statuses = list_statuses(root)
    except PackageRegistryError as exc:
        print(format_console('error', str(exc)), file=sys.stderr)
        return 1
    if not statuses:
        print(format_console('info', 'Пакеты в реестре не найдены'))
        return 0

    # SOURCE с module длиннее source.value — считаем по фактическим подписям
    source_labels = [
        f'{st.source.value}:{st.module}' if st.module else st.source.value
        for st in statuses
    ]
    name_w = max(len(s.name) for s in statuses)
    src_w = max(len(label) for label in source_labels)
    print(f'{"NAME":<{name_w}}  {"SOURCE":<{src_w}}  INSTALLED  VERSION  PATH')
    for st, src in zip(statuses, source_labels):
        installed = 'yes' if st.installed else ('n/a' if not st.platform_supported else 'no')
        version = st.version or '-'
        print(
            f'{st.name:<{name_w}}  {src:<{src_w}}  {installed:<9}  {version:<7}  {st.path}'
        )
    return 0


def cmd_status(root: Path, name: str | None) -> int:
    try:
        if name:
            spec = get_package(root, name)
            if spec is None:
                print(format_console('error', f'Пакет не найден: {name}'), file=sys.stderr)
                return 1
            statuses = [status_for(root, spec)]
        else:
            statuses = list_statuses(root)
    except PackageRegistryError as exc:
        print(format_console('error', str(exc)), file=sys.stderr)
        return 1

    for st in statuses:
        print(f'name: {st.name}')
        print(f'  source: {st.source.value}' + (f' ({st.module})' if st.module else ''))
        print(f'  kind: {st.kind.value}')
        print(f'  version: {st.version or "-"}')
        print(f'  path: {st.path}')
        print(f'  marker: {st.marker or "-"}')
        print(f'  platform_supported: {"yes" if st.platform_supported else "no"}')
        print(f'  installed: {"yes" if st.installed else "no"}')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Реестр portable-пакетов ERGO MS')
    parser.add_argument('--root', type=Path, default=None, help='Корень проекта')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('list', help='Список пакетов реестра')
    requirements = sub.add_parser('requirements', help='Проверить runtime_requirements.yaml')
    requirements.add_argument('--json', action='store_true')
    required = sub.add_parser('install-required', help='Установить обязательные инструменты модулей')
    required.add_argument('--include-optional', action='store_true')

    p_status = sub.add_parser('status', help='Статус пакета или всех')
    p_status.add_argument('name', nargs='?', default=None, help='Имя пакета')

    p_install = sub.add_parser('install', help='Установить пакет')
    p_install.add_argument('name', help='Имя пакета')
    p_install.add_argument('--force', action='store_true', help='Переустановить')
    p_install.add_argument(
        '--refresh',
        action='store_true',
        help='Скачать архив заново (игнорировать кэш)',
    )

    p_uninstall = sub.add_parser('uninstall', help='Удалить пакет')
    p_uninstall.add_argument('name', help='Имя пакета')
    p_uninstall.add_argument(
        '--purge-extra',
        action='store_true',
        help='Также удалить extra_dirs из манифеста',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    root = _resolve_root(args.root)

    if args.command in ('requirements', 'install-required'):
        try:
            if args.command == 'install-required':
                return install_required_tools(root, include_optional=args.include_optional)
            plan = resolve_plan(root)
            if args.json:
                print(json.dumps(plan, ensure_ascii=False))
            else:
                for entry in plan['tools']:
                    policy = 'required' if entry['required'] else 'optional'
                    print(f"{entry['name']}: {policy} ({', '.join(entry['modules'])})")
                print('Python groups: ' + ', '.join(plan['python_groups']))
                print(format_console('ok', 'runtime_requirements.yaml проверены'))
            return 0
        except (RuntimeRequirementsError, PackageRegistryError) as exc:
            print(format_console('error', str(exc)), file=sys.stderr)
            return 1
    if args.command == 'list':
        return cmd_list(root)
    if args.command == 'status':
        return cmd_status(root, args.name)
    if args.command == 'install':
        return install_package(
            root,
            args.name,
            force=bool(args.force),
            refresh=bool(args.refresh),
        )
    if args.command == 'uninstall':
        return uninstall_package(
            root,
            args.name,
            purge_extra=bool(args.purge_extra),
        )
    parser.error(f'Неизвестная команда: {args.command}')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
