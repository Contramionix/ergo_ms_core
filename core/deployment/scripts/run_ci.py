#!/usr/bin/env python3
"""Быстрые проверки ergoms ci и строгий ночной прогон ergoms ci-nightly."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_DEPLOYMENT_DIR = _SCRIPTS_DIR.parent
_PROJECT_ROOT = _DEPLOYMENT_DIR.parent.parent

for _path in (_DEPLOYMENT_DIR, _SCRIPTS_DIR):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from cli_locale import t  # noqa: E402
from console_tags import configure_stdio_utf8, format_console  # noqa: E402
from project_layout import (  # noqa: E402
    nodejs_exe,
    npm_exe,
    prepend_client_cli_path,
)

LOCK_STEP_LABELS = (
    'poetry.lock',
    'package-lock.json',
)
PARALLEL_STEP_LABELS = (
    'core-rules-check',
    'system-test unit',
    'lint:check',
    'client-tests',
)
FAST_STEP_LABELS = LOCK_STEP_LABELS + PARALLEL_STEP_LABELS

_NIGHTLY = (
    ('scenarios', ('--spec', 'host_sqlite_direct')),
    ('scenarios', ('--spec', 'docker_direct')),
    ('security', ()),
    ('browser', ()),
)


def _nightly_label(suite: str, extra: tuple[str, ...]) -> str:
    spec = ''
    if '--spec' in extra:
        spec = extra[extra.index('--spec') + 1]
    if spec:
        return f'system-test {suite} {spec}'
    return f'system-test {suite}'


def nightly_step_labels() -> tuple[str, ...]:
    return tuple(_nightly_label(suite, extra) for suite, extra in _NIGHTLY)


def _relative_lint_path(file_path: str, root: Path) -> str:
    path = Path(file_path)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def lint_findings(
    payload: object,
    root: Path,
) -> tuple[list[tuple[str, int, str, str]], list[tuple[str, int]]]:
    """Ошибки со строкой файла и число предупреждений по правилу.

    Полный список предупреждений в консоли прячет границу шага ergoms ci.
    """
    if not isinstance(payload, list):
        raise ValueError('eslint report is not a list')
    errors: list[tuple[str, int, str, str]] = []
    warning_counts: dict[str, int] = {}
    for file_result in payload:
        if not isinstance(file_result, dict):
            continue
        rel = _relative_lint_path(str(file_result.get('filePath') or ''), root)
        messages = file_result.get('messages') or []
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            rule = str(message.get('ruleId') or 'syntax')
            severity = message.get('severity')
            if severity == 2:
                line = int(message.get('line') or 0)
                text = ' '.join(str(message.get('message') or '').split())
                errors.append((rel, line, rule, text))
            elif severity == 1:
                warning_counts[rule] = warning_counts.get(rule, 0) + 1
    errors.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    warnings = sorted(warning_counts.items(), key=lambda item: (-item[1], item[0]))
    return errors, warnings


def _line_buffer_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is None:
            continue
        try:
            reconfigure(line_buffering=True)
        except (OSError, ValueError):
            continue


def _emit(level: str, message: str, *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    print(format_console(level, message), file=stream, flush=True)


def _child_env(env: dict[str, str] | None) -> dict[str, str]:
    child = os.environ.copy() if env is None else dict(env)
    child['PYTHONUNBUFFERED'] = '1'
    return child


_DJANGO_LOG = re.compile(r'^\[(?:INFO|WARNING|ERROR|DEBUG)\] \d{4}-\d{2}-\d{2}\s')


def keep_rules_line(line: str) -> bool:
    """В ergoms ci не повторять журнал старта Django: проверка и так пишет свой итог."""
    text = line.strip()
    if text.startswith('Выполняется Django команда:'):
        return False
    return _DJANGO_LOG.match(text) is None


def unit_success_lines(text: str) -> list[str]:
    """Из тихого прогона unittest оставить только итог."""
    found: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('Ran ') or stripped.startswith('OK'):
            found.append(stripped)
    return found


_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
_CLIENT_COUNT = re.compile(
    r'^\u2139\s+(tests|suites|pass|fail|cancelled|skipped|todo|duration_ms)\s+'
    r'(\d+(?:\.\d+)?)\s*$'
)


def strip_console_controls(text: str) -> str:
    """Убрать последовательности, которыми отчёт Node двигает курсор."""
    return _ANSI_RE.sub('', text)


def _client_pass_line(line: str) -> bool:
    return line.lstrip().startswith(('✔', '✓'))


def client_report_lines(text: str, code: int) -> list[str]:
    """Успех — одна строка счёта. Падение — отчёт без прошедших тестов и без ANSI."""
    counts: dict[str, int] = {}
    body: list[str] = []
    summary: list[str] = []
    for raw in strip_console_controls(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _CLIENT_COUNT.match(line)
        if match is not None:
            name = match.group(1)
            if name != 'duration_ms':
                counts[name] = int(float(match.group(2)))
            summary.append(line)
            continue
        if _client_pass_line(line):
            continue
        body.append(line)
    passed_cleanly = (
        code == 0
        and not body
        and 'tests' in counts
        and 'pass' in counts
        and counts.get('fail') == 0
        and counts.get('cancelled', 0) == 0
        and counts.get('todo', 0) == 0
    )
    if passed_cleanly:
        tests = counts['tests']
        passed = counts['pass']
        skipped = counts.get('skipped', 0)
        if skipped:
            return [
                t(
                    'ci_client_tests_tally_skipped',
                    tests=tests,
                    passed=passed,
                    skipped=skipped,
                )
            ]
        return [t('ci_client_tests_tally', tests=tests, passed=passed)]
    if code == 0 and not body:
        return summary
    return body + summary


def _capture(argv: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, str]:
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    text = proc.stdout or ''
    if proc.stderr:
        text = f'{text}{proc.stderr}'
    return proc.returncode, text


def _run(
    label: str,
    argv: list[str],
    *,
    cwd: Path,
    index: int,
    total: int,
    env: dict[str, str] | None = None,
) -> int:
    print(flush=True)
    _emit('info', t('ci_step_start', index=index, total=total, label=label))
    started = time.monotonic()
    code = subprocess.call(argv, cwd=str(cwd), env=_child_env(env))
    seconds = int(time.monotonic() - started)
    if code != 0:
        _emit(
            'error',
            t('ci_step_failed', label=label, code=code, seconds=seconds),
            error=True,
        )
        return code
    _emit('ok', t('ci_step_ok', label=label, seconds=seconds))
    return 0


def _node_binary(root: Path) -> Path | None:
    portable = nodejs_exe(root)
    if portable.is_file():
        return portable
    return None


def _npm_binary(root: Path) -> str | None:
    portable = npm_exe(root)
    if portable.is_file():
        return str(portable)
    return None


def _fast_steps(root: Path) -> int:
    py = sys.executable
    scripts = root / 'core' / 'deployment' / 'scripts'
    node = _node_binary(root)
    npm = _npm_binary(root)
    if node is None or npm is None:
        _emit('error', t('ci_node_missing'), error=True)
        return 1

    total = len(FAST_STEP_LABELS)
    _emit('info', t('ci_run_start', count=total))
    commands: dict[str, tuple[list[str], Path, dict[str, str] | None]] = {
        'poetry.lock': ([py, str(scripts / 'validate_poetry_lock.py')], root, None),
        'package-lock.json': ([str(node), str(scripts / 'validate_npm_lock.js')], root, None),
    }
    for label in LOCK_STEP_LABELS:
        argv, cwd, env = commands[label]
        code = _run(
            label,
            argv,
            cwd=cwd,
            index=FAST_STEP_LABELS.index(label) + 1,
            total=total,
            env=env,
        )
        if code != 0:
            return code

    print(flush=True)
    _emit('info', t('ci_parallel_start'))
    codes: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=len(PARALLEL_STEP_LABELS)) as pool:
        futures = [
            pool.submit(_perform, root, node, scripts, py, label)
            for label in PARALLEL_STEP_LABELS
        ]
        for future in as_completed(futures):
            label, code, lines, seconds = future.result()
            _announce(
                label,
                index=FAST_STEP_LABELS.index(label) + 1,
                total=total,
                code=code,
                lines=lines,
                seconds=seconds,
            )
            codes[label] = code
    for label in PARALLEL_STEP_LABELS:
        code = codes.get(label, 1)
        if code != 0:
            return code
    return 0


def _announce(
    label: str,
    *,
    index: int,
    total: int,
    code: int,
    lines: list[str],
    seconds: int,
) -> None:
    if label in PARALLEL_STEP_LABELS:
        heading = t('ci_parallel_step', label=label)
    else:
        heading = t('ci_step_start', index=index, total=total, label=label)
    parts = [format_console('info', heading)]
    parts.extend(strip_console_controls(line) for line in lines)
    if code != 0:
        parts.append(
            format_console(
                'error',
                t('ci_step_failed', label=label, code=code, seconds=seconds),
            )
        )
    else:
        parts.append(format_console('ok', t('ci_step_ok', label=label, seconds=seconds)))
    print('\n' + '\n'.join(parts), flush=True)


def _perform(
    root: Path,
    node: Path,
    scripts: Path,
    py: str,
    label: str,
) -> tuple[str, int, list[str], int]:
    started = time.monotonic()
    if label == 'lint:check':
        code, lines = _collect_lint(root, node)
    elif label == 'client-tests':
        code, lines = _collect_client_tests(root, node, scripts)
    elif label == 'system-test unit':
        code, lines = _collect_unit(root, py, scripts)
    elif label == 'core-rules-check':
        code, lines = _collect_rules(root, py, scripts)
    else:
        code, lines = 1, [label]
    return label, code, lines, int(time.monotonic() - started)


def _collect_rules(root: Path, py: str, scripts: Path) -> tuple[int, list[str]]:
    proc = subprocess.run(
        [py, str(scripts / 'validate_core_rules.py')],
        cwd=str(root),
        env=_child_env(None),
        capture_output=True,
        encoding='utf-8',
        errors='replace',
    )
    text = f'{proc.stdout or ""}{proc.stderr or ""}'
    lines = [line for line in text.splitlines() if keep_rules_line(line)]
    return proc.returncode, lines


def _collect_unit(root: Path, py: str, scripts: Path) -> tuple[int, list[str]]:
    code, text = _capture(
        [py, str(scripts / 'run_system_test.py'), '--suite', 'unit'],
        root,
        _child_env(None),
    )
    if code != 0:
        return code, text.splitlines()
    return 0, unit_success_lines(text)


def client_test_files(root: Path, disabled: frozenset[str] | None = None) -> list[Path]:
    """Тесты клиента модулей, которые не выключены в DISABLED_MODULES."""
    if disabled is None:
        from lifecycle.modules.catalog import ModuleCatalog

        disabled = ModuleCatalog.from_project_env(root).disabled
    tests = sorted(root.glob('modules/*/client/tests/**/*.test.mjs'))
    if not disabled:
        return tests
    kept: list[Path] = []
    root_resolved = root.resolve()
    for path in tests:
        try:
            parts = path.resolve().relative_to(root_resolved).parts
        except ValueError:
            kept.append(path)
            continue
        if len(parts) >= 2 and parts[0] == 'modules' and parts[1] in disabled:
            continue
        kept.append(path)
    return kept


def _lint_lines(
    errors: list[tuple[str, int, str, str]],
    warnings: list[tuple[str, int]],
) -> list[str]:
    lines: list[str] = []
    if errors:
        lines.append(format_console('error', t('ci_lint_errors', count=len(errors))))
        lines.extend(
            f'  {path}:{line}  {rule}  {message}'
            for path, line, rule, message in errors
        )
    if warnings:
        total = sum(count for _, count in warnings)
        width = max(len(rule) for rule, _ in warnings)
        lines.append(format_console('warning', t('ci_lint_warnings', count=total)))
        lines.extend(f'  {rule.ljust(width)}  {count}' for rule, count in warnings)
    if not errors and not warnings:
        lines.append(format_console('ok', t('ci_lint_clean')))
    return lines


def _collect_lint(root: Path, node: Path) -> tuple[int, list[str]]:
    script = root / 'core' / 'client' / 'scripts' / 'run-eslint-check.js'
    proc = subprocess.run(
        [str(node), str(script), '--report=json'],
        cwd=str(root),
        env=_child_env(prepend_client_cli_path(os.environ.copy(), root)),
        capture_output=True,
        encoding='utf-8',
        errors='replace',
    )
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else []
        errors, warnings = lint_findings(payload, root)
    except (json.JSONDecodeError, ValueError, TypeError):
        detail = (proc.stderr or proc.stdout or '').strip()
        lines = [detail] if detail else []
        lines.append(format_console('error', t('ci_lint_report_broken')))
        code = proc.returncode if proc.returncode else 1
        return code, lines
    code = proc.returncode
    if errors and code == 0:
        code = 1
    return code, _lint_lines(errors, warnings)


def _collect_client_tests(root: Path, node: Path, scripts: Path) -> tuple[int, list[str]]:
    tests = client_test_files(root)
    if not tests:
        return 0, [
            format_console(
                'skip',
                t('ci_step_skipped', label='client-tests', detail=t('ci_client_tests_none')),
            )
        ]
    loader = (scripts / 'resolve_workspace_modules.mjs').as_uri()
    proc = subprocess.run(
        [str(node), '--import', loader, '--test', *[str(path) for path in tests]],
        cwd=str(root),
        env=_child_env(None),
        capture_output=True,
        encoding='utf-8',
        errors='replace',
    )
    text = f'{proc.stdout or ""}{proc.stderr or ""}'
    return proc.returncode, client_report_lines(text, proc.returncode)


def _nightly(root: Path) -> int:
    labels = nightly_step_labels()
    total = len(labels)
    script = root / 'core' / 'deployment' / 'scripts' / 'run_system_test.py'
    for index, ((suite, extra), label) in enumerate(zip(_NIGHTLY, labels, strict=True), start=1):
        code = _run(
            label,
            [sys.executable, str(script), '--suite', suite, '--strict', *extra],
            cwd=root,
            index=index,
            total=total,
        )
        if code != 0:
            return code
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Fast ERGO MS checks')
    parser.add_argument('--nightly', action='store_true')
    args = parser.parse_args(argv)
    configure_stdio_utf8()
    _line_buffer_stdio()
    code = _fast_steps(_PROJECT_ROOT)
    if code != 0:
        return code
    if args.nightly:
        print(format_console('ok', t('ci_finished')), flush=True)
        print(flush=True)
        print(
            format_console('info', t('ci_nightly_start', count=len(nightly_step_labels()))),
            flush=True,
        )
        code = _nightly(_PROJECT_ROOT)
        if code != 0:
            return code
        print(format_console('ok', t('ci_nightly_finished')), flush=True)
        return 0
    print(format_console('ok', t('ci_finished')), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
