"""
Справка ergoms: ядро, модули, отдельный модуль.

  ergoms help
  ergoms help modules
  ergoms help module <имя>

Язык: ERGO_CLI_LANGUAGE → системная локаль → ru (cli_locale.py).
Source of truth — русские строки в help YAML; переводы — locales/<lang>/ overlays.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Any

_DEPLOYMENT_DIR = Path(__file__).resolve().parent.parent
if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))

from cli_locale import (  # noqa: E402
    ensure_project_env_loaded,
    load_localized_yaml,
    localize_value,
    module_help_overlay_path,
    resolve_cli_language,
    t,
)

_MANIFEST_PATH = _DEPLOYMENT_DIR / 'help.manifest.yaml'

_CONF_LINE = re.compile(r'^([a-zA-Z0-9_-]+)=(.+)$')

_BUILTIN_COMMANDS = frozenset({
    'help', 'install', 'install-services', 'install-api-service', 'install-client-service',
    'install-worker-service', 'install-beat-service', 'install-media-service',
    'start', 'stop', 'restart', 'status', 'uninstall-services',
    'install-cli', 'uninstall-cli', 'logs', 'setup-full', 'clean',
    'update-submodules', 'update-module-submodules',
    'install-nginx', 'install-nginx-service', 'uninstall-nginx',
    'start-nginx', 'stop-nginx', 'restart-nginx', 'reload-nginx',
    'status-nginx', 'test-nginx',
    'install-redis', 'install-redis-service', 'uninstall-redis',
    'start-redis', 'stop-redis', 'restart-redis', 'status-redis', 'test-redis',
    'install-meilisearch', 'install-meilisearch-service', 'uninstall-meilisearch',
    'start-meilisearch', 'stop-meilisearch', 'restart-meilisearch',
    'status-meilisearch', 'test-meilisearch', 'search-reindex',
    'install-postgres', 'install-postgres-service', 'uninstall-postgres',
    'start-postgres', 'stop-postgres', 'restart-postgres', 'status-postgres', 'test-postgres',
    'migrate-postgres-to-portable',
    'install-tls', 'renew-tls', 'status-tls',
    'deploy-api', 'deploy-client', 'deploy-api-dev', 'deploy-client-dev', 'deploy-all',
})

_PLATFORM_LABELS = {
    'windows': 'Windows',
    'linux': 'Linux',
}


def _resolve_project_root(explicit: str | None) -> Path:
    if explicit:
        root = Path(explicit).resolve()
        if not root.is_dir():
            raise SystemExit(t('help_root_not_found', root=root))
        return root

    candidate = _DEPLOYMENT_DIR.parent.parent
    if (candidate / 'pyproject.toml').is_file():
        return candidate

    raise SystemExit(t('help_root_resolve_failed'))


def _parse_conf_commands(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}

    commands: dict[str, str] = {}
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or line.startswith('='):
            continue
        match = _CONF_LINE.match(line)
        if match:
            commands[match.group(1).strip()] = match.group(2).strip()
    return commands


def _load_manifest(lang: str) -> dict[str, Any]:
    if not _MANIFEST_PATH.is_file():
        raise SystemExit(t('help_manifest_missing', path=_MANIFEST_PATH))
    data = load_localized_yaml(_MANIFEST_PATH, lang)
    if not isinstance(data, dict):
        raise SystemExit(t('help_manifest_invalid'))
    return data


def _discover_module_confs(root: Path) -> dict[str, dict[str, str]]:
    modules: dict[str, dict[str, str]] = {}
    modules_dir = root / 'modules'
    if not modules_dir.is_dir():
        return modules

    for module_dir in sorted(modules_dir.iterdir()):
        if not module_dir.is_dir():
            continue
        conf_path = module_dir / 'ergoms.conf'
        if conf_path.is_file():
            commands = _parse_conf_commands(conf_path)
            if commands:
                modules[module_dir.name] = commands
    return modules


def _load_module_help_yaml(module_dir: Path, lang: str) -> dict[str, Any] | None:
    help_path = module_dir / 'ergoms.help.yaml'
    if not help_path.is_file():
        return None
    data = load_localized_yaml(
        help_path,
        lang,
        overlay_path=module_help_overlay_path(module_dir, lang),
    )
    return data if isinstance(data, dict) else None


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def _command_exists(name: str, conf_commands: dict[str, str]) -> bool:
    return name in conf_commands or name in _BUILTIN_COMMANDS


def _command_invoke(name: str, item: dict[str, Any] | None = None) -> str:
    if item and item.get('invoke'):
        return str(item['invoke']).strip()
    return f'ergoms {name}'


_LABEL_WIDTH = 42
_SUMMARY_COLUMN = 45
_MIN_SUMMARY = 24


def _terminal_columns(width: int | None) -> int:
    if width is not None:
        return width
    return shutil.get_terminal_size(fallback=(80, 24)).columns


def _wrap_words(text: str, width: int) -> list[str]:
    # Флаг вроде --module=<name> не режется посередине.
    return textwrap.wrap(
        text,
        max(width, 1),
        break_long_words=False,
        break_on_hyphens=False,
    )


def _format_command_line(
    name: str,
    summary: str,
    *,
    invoke: str | None = None,
    columns: int | None = None,
) -> str:
    label = invoke or f'ergoms {name}'
    window = _terminal_columns(columns)
    if window - _SUMMARY_COLUMN < _MIN_SUMMARY:
        return _format_stacked_command(label, summary, window)
    summary_lines = _wrap_words(summary, window - _SUMMARY_COLUMN) if summary else []
    # Вызов с длинным списком флагов не влезает в колонку и сдвигает описание.
    if len(label) <= _LABEL_WIDTH:
        if not summary_lines:
            return f'  {label}'
        lines = [f'  {label.ljust(_LABEL_WIDTH)} {summary_lines[0]}']
    else:
        lines = [f'  {part}' for part in _wrap_words(label, window - 2)]
    lines.extend(f'{" " * _SUMMARY_COLUMN}{part}' for part in summary_lines[1 if len(label) <= _LABEL_WIDTH else 0:])
    return '\n'.join(lines)


def _format_stacked_command(label: str, summary: str, columns: int) -> str:
    lines = [f'  {part}' for part in _wrap_words(label, columns - 2)]
    if summary:
        lines.extend(f'    {part}' for part in _wrap_words(summary, columns - 4))
    return '\n'.join(lines)


def _as_text(value: Any) -> str:
    """Строка из уже локализованного YAML (legacy nested map — через localize_value)."""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return localize_value(value)


def _render_section_commands(
    section: dict[str, Any],
    conf_commands: dict[str, str],
    *,
    validate: bool,
    lang: str,
    columns: int,
) -> list[str]:
    lines: list[str] = []
    title = _as_text(section.get('title'))
    if title:
        lines.append(title)

    note = _as_text(section.get('note'))
    if note:
        lines.append(f'  {note}')

    for item in section.get('commands') or []:
        if isinstance(item, str):
            name, summary, entry = item, '', None
        else:
            name = item.get('name', '')
            summary = _as_text(item.get('summary'))
            entry = item
        if validate and name and not _command_exists(name, conf_commands):
            _warn(t('help_warn_command_missing', name=name, lang=lang))
        if name:
            lines.append(_format_command_line(
                name,
                summary,
                invoke=_command_invoke(name, entry),
                columns=columns,
            ))

    for static_line in section.get('static_lines') or []:
        text = _as_text(static_line)
        if text:
            lines.append(f'  {text}')

    return lines


def render_core(
    root: Path,
    platform: str,
    lang: str | None = None,
    *,
    width: int | None = None,
) -> str:
    language = lang or resolve_cli_language(project_root=root)
    manifest = _load_manifest(language)
    conf_commands = _parse_conf_commands(root / 'core' / 'deployment' / 'commands.conf')
    platform_label = _PLATFORM_LABELS.get(platform, platform)
    columns = _terminal_columns(width)

    out: list[str] = [
        t('help_title', lang=language, platform=platform_label),
        '=' * (18 + len(platform_label)),
        '',
    ]

    for section in manifest.get('sections') or []:
        block = _render_section_commands(
            section, conf_commands, validate=True, lang=language, columns=columns,
        )
        if block:
            out.extend(block)
            out.append('')

    for section in (manifest.get('platform_sections') or {}).get(platform) or []:
        block = _render_section_commands(
            section, conf_commands, validate=True, lang=language, columns=columns,
        )
        if block:
            out.extend(block)
            out.append('')

    scenarios = manifest.get('scenarios') or []
    if scenarios:
        out.append(t('help_scenarios_heading', lang=language))
        for scenario in scenarios:
            out.append(f'  {_as_text(scenario.get("title"))}')
            for line in scenario.get('lines') or []:
                text = _as_text(line)
                if text:
                    out.append(f'    {text}')
        out.append('')

    footer = manifest.get('footer') or {}
    doc = footer.get('doc')
    config = footer.get('config')
    if doc:
        out.append(t('help_more', lang=language, doc=doc))
    if config:
        out.append(t('help_config', lang=language, config=config))

    return '\n'.join(out).rstrip() + '\n'


_WORDMARK = (
    '░██████████                                ░███     ░███   ░██████',
    '░██                                        ░████   ░████  ░██   ░██',
    '░██         ░██░████  ░████████  ░███████  ░██░██ ░██░██ ░██',
    '░█████████  ░███     ░██    ░██ ░██    ░██ ░██ ░████ ░██  ░████████',
    '░██         ░██      ░██    ░██ ░██    ░██ ░██  ░██  ░██         ░██',
    '░██         ░██      ░██   ░███ ░██    ░██ ░██       ░██  ░██   ░██',
    '░██████████ ░██       ░█████░██  ░███████  ░██       ░██   ░██████',
    '                            ░██',
    '                      ░███████',
)
_WORDMARK_WIDTH = max(len(line) for line in _WORDMARK)
_GROUP_ORDER = ('work', 'build', 'env', 'other')


def _section_label(section: dict[str, Any]) -> str:
    """Имя, которое человек набирает в ergoms help. Поле help короче внутреннего id."""
    return str(section.get('help') or section.get('id') or '').strip()


def _section_matches(section: dict[str, Any], name: str) -> bool:
    return name in {str(section.get('id') or '').strip(), _section_label(section)}


def _catalog_sections(manifest: dict[str, Any], platform: str) -> list[dict[str, Any]]:
    sections = [item for item in (manifest.get('sections') or []) if isinstance(item, dict)]
    platform_sections = (manifest.get('platform_sections') or {}).get(platform) or []
    sections.extend(item for item in platform_sections if isinstance(item, dict))
    return sections


def _render_scenarios(manifest: dict[str, Any], language: str) -> str:
    out = [t('help_scenarios_heading', lang=language), '']
    for scenario in manifest.get('scenarios') or []:
        out.append(f'  {_as_text(scenario.get("title"))}')
        for line in scenario.get('lines') or []:
            text = _as_text(line)
            if text:
                out.append(f'    {text}')
        out.append('')
    return '\n'.join(out).rstrip() + '\n'


def _overview_rows(
    manifest: dict[str, Any],
    platform: str,
    language: str,
) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for section in _catalog_sections(manifest, platform):
        label = _section_label(section)
        about = _as_text(section.get('about')) or _as_text(section.get('title'))
        if label and about:
            group = str(section.get('group') or 'other')
            rows.append((group, label, about))
    if manifest.get('scenarios'):
        rows.append(('other', 'scenarios', t('help_scenarios_about', lang=language)))
    order = {name: index for index, name in enumerate(_GROUP_ORDER)}
    rows.sort(key=lambda row: order.get(row[0], len(order)))
    return rows


def render_overview(
    root: Path,
    platform: str,
    lang: str | None = None,
    *,
    width: int | None = None,
) -> str:
    """Оглавление: имя раздела и его заголовок, без списка команд."""
    language = lang or resolve_cli_language(project_root=root)
    manifest = _load_manifest(language)
    platform_label = _PLATFORM_LABELS.get(platform, platform)
    columns = width if width is not None else shutil.get_terminal_size(fallback=(80, 24)).columns
    title = t('help_title', lang=language, platform=platform_label)
    out: list[str] = []
    # Длинный рисунок в узком окне переносится по краю и ломает буквы.
    # Пустая строка сверху отделяет буквы от приглашения оболочки.
    if columns >= _WORDMARK_WIDTH:
        out.append('')
        out.extend(_WORDMARK)
        out.append('')
    out.extend([title, ''])
    hints = (
        (t('help_hint_section', lang=language), t('help_hint_section_text', lang=language)),
        (t('help_hint_all', lang=language), t('help_hint_all_text', lang=language)),
        (t('help_hint_modules', lang=language), t('help_hint_modules_text', lang=language)),
    )
    hint_width = max(len(command) for command, _text in hints) + 2
    for command, text in hints:
        out.append(f'  {command.ljust(hint_width)} {text}')
    out.append('')
    rows = _overview_rows(manifest, platform, language)
    column = max((len(label) for _group, label, _title in rows), default=0) + 2
    current = ''
    for group, label, section_title in rows:
        if group != current:
            if current:
                out.append('')
            out.append(t(f'help_group_{group}', lang=language))
            current = group
        out.append(f'  {label.ljust(column)} — {section_title}')
    doc = (manifest.get('footer') or {}).get('doc')
    if doc:
        out.append('')
        out.append(t('help_more', lang=language, doc=doc))
    return '\n'.join(out).rstrip() + '\n'


def render_section(
    root: Path,
    platform: str,
    section_id: str,
    lang: str | None = None,
    *,
    width: int | None = None,
) -> str:
    language = lang or resolve_cli_language(project_root=root)
    manifest = _load_manifest(language)
    if section_id == 'scenarios':
        return _render_scenarios(manifest, language)
    conf_commands = _parse_conf_commands(root / 'core' / 'deployment' / 'commands.conf')
    columns = _terminal_columns(width)
    for section in _catalog_sections(manifest, platform):
        if _section_matches(section, section_id):
            block = _render_section_commands(
                section, conf_commands, validate=True, lang=language, columns=columns,
            )
            return '\n'.join(block).rstrip() + '\n'
    raise SystemExit(t('help_unknown_section', lang=language, name=section_id))


def render_modules(root: Path, lang: str | None = None, *, width: int | None = None) -> str:
    language = lang or resolve_cli_language(project_root=root)
    columns = _terminal_columns(width)
    module_confs = _discover_module_confs(root)
    if not module_confs:
        return t('help_modules_empty', lang=language) + '\n'

    out = [
        t('help_modules_heading', lang=language),
        '=========================',
        '',
    ]

    for module_name, conf_commands in module_confs.items():
        module_dir = root / 'modules' / module_name
        help_data = _load_module_help_yaml(module_dir, language)
        count = len(conf_commands)

        if help_data:
            title = _as_text(help_data.get('title')) or module_name
            summary = _as_text(help_data.get('summary')) or ''
            label = t('help_modules_count', lang=language, title=title, count=count)
            if summary and summary not in label:
                label = t(
                    'help_modules_count_summary',
                    lang=language,
                    title=title,
                    count=count,
                    summary=summary,
                )
            out.append(_format_command_line(module_name, label, columns=columns))
        else:
            out.append(_format_command_line(
                module_name,
                t('help_modules_no_yaml', lang=language, count=count),
                columns=columns,
            ))

    out.extend([
        '',
        t('help_modules_more', lang=language),
    ])
    return '\n'.join(out) + '\n'


def render_module(
    root: Path,
    module_name: str,
    lang: str | None = None,
    *,
    width: int | None = None,
) -> str:
    language = lang or resolve_cli_language(project_root=root)
    columns = _terminal_columns(width)
    module_confs = _discover_module_confs(root)
    if module_name not in module_confs:
        names = ', '.join(sorted(module_confs)) or '—'
        raise SystemExit(
            t('help_module_not_found', lang=language, name=module_name, names=names),
        )

    module_dir = root / 'modules' / module_name
    conf_commands = module_confs[module_name]
    help_data = _load_module_help_yaml(module_dir, language) or {}

    if help_data.get('module') and help_data['module'] != module_name:
        _warn(t(
            'help_warn_module_mismatch',
            lang=language,
            declared=help_data['module'],
            name=module_name,
        ))

    title = _as_text(help_data.get('title')) or module_name
    summary = _as_text(help_data.get('summary')) or ''

    out = [
        t('help_module_heading', lang=language, name=module_name),
        f'{title}',
        '',
    ]
    if summary:
        out.append(summary)
        out.append('')

    help_commands = help_data.get('commands') or {}
    if not isinstance(help_commands, dict):
        help_commands = {}

    for cmd_name in sorted(conf_commands):
        cmd_summary = ''
        entry = help_commands.get(cmd_name)
        if isinstance(entry, dict):
            cmd_summary = _as_text(entry.get('summary'))
        elif isinstance(entry, str):
            cmd_summary = entry
        elif entry is not None:
            cmd_summary = str(entry)

        if not cmd_summary:
            cmd_summary = t('help_summary_missing', lang=language)
            _warn(t(
                'help_warn_no_summary',
                lang=language,
                cmd=cmd_name,
                module=module_name,
            ))

        full_name = f'{module_name}:{cmd_name}'
        out.append(_format_command_line(
            cmd_name,
            cmd_summary,
            invoke=f'ergoms {full_name}',
            columns=columns,
        ))
        out.append('')

    for key in sorted(help_commands):
        if key not in conf_commands:
            _warn(t('help_warn_extra_command', lang=language, key=key))

    notes = help_data.get('notes') or []
    if notes:
        out.append(t('help_notes_heading', lang=language))
        for note in notes:
            text = _as_text(note)
            if text:
                out.append(f'  - {text}')
        out.append('')

    if not help_data:
        out.append(t('help_add_yaml', lang=language, name=module_name))

    return '\n'.join(out).rstrip() + '\n'


def resolve_help_subargs(help_subargs: list[str], lang: str | None = None) -> tuple[str, str | None]:
    language = lang or resolve_cli_language()
    if not help_subargs:
        return 'overview', None
    if len(help_subargs) == 1 and help_subargs[0] == 'modules':
        return 'modules', None
    if len(help_subargs) == 1 and help_subargs[0] == 'all':
        return 'all', None
    if len(help_subargs) >= 2 and help_subargs[0] == 'module':
        return 'module', help_subargs[1]
    if len(help_subargs) == 1 and help_subargs[0] == 'module':
        raise SystemExit(t('help_module_name_required', lang=language))
    if len(help_subargs) == 1:
        return 'section', help_subargs[0]
    raise SystemExit(t(
        'help_unknown_args',
        lang=language,
        args=' '.join(help_subargs),
    ))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='ergoms help')
    parser.add_argument('--root', help='ERGO MS project root')
    parser.add_argument(
        '--platform',
        choices=('windows', 'linux'),
        default='windows' if sys.platform == 'win32' else 'linux',
    )
    parser.add_argument(
        'help_subargs',
        nargs='*',
        help='all | <section> | modules | module <name>',
    )
    return parser


def _configure_stdout_utf8() -> None:
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError, ValueError):
            pass
    if hasattr(sys.stderr, 'reconfigure'):
        try:
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError, ValueError):
            pass


def main() -> int:
    _configure_stdout_utf8()
    parser = _build_parser()
    args = parser.parse_args()
    root = _resolve_project_root(args.root)
    ensure_project_env_loaded(root)
    lang = resolve_cli_language(project_root=root)
    mode, target = resolve_help_subargs(args.help_subargs, lang)

    if mode == 'overview':
        sys.stdout.write(render_overview(root, args.platform, lang))
        return 0

    if mode == 'all':
        sys.stdout.write(render_core(root, args.platform, lang))
        return 0

    if mode == 'section':
        assert target is not None
        sys.stdout.write(render_section(root, args.platform, target, lang))
        return 0

    if mode == 'modules':
        sys.stdout.write(render_modules(root, lang))
        return 0

    if mode == 'module':
        assert target is not None
        sys.stdout.write(render_module(root, target, lang))
        return 0

    raise SystemExit(t('help_unknown_mode', lang=lang, mode=mode))


if __name__ == '__main__':
    raise SystemExit(main())
