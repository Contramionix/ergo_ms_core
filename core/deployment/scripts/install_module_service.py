"""Установка OS-службы API/worker/beat модуля без хардкода имён в ядре.

Использование: ergoms install-module-service --module=<name> --kind=api|worker|beat
               ergoms uninstall-module-service --module=<name> --kind=api|worker|beat
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_DEPLOYMENT_DIR = _SCRIPTS_DIR.parent
PROJECT_ROOT = _DEPLOYMENT_DIR.parent.parent

if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))

from cli_locale import t  # noqa: E402
from console_tags import configure_stdio_utf8, format_console  # noqa: E402
from project_layout import ensure_dir  # noqa: E402
from sh_io import write_sh  # noqa: E402

WRAPPERS = PROJECT_ROOT / 'core' / 'deployment' / 'wrappers'


def _safe(name: str) -> str:
    return ''.join(ch if ch.isalnum() or ch == '_' else '_' for ch in name)


def _service_name(module: str, kind: str, worker_id: str = '') -> str:
    from service_names import names_from_root

    names = names_from_root(PROJECT_ROOT)
    if kind == 'worker' and worker_id:
        return names.module_worker(module, worker_id)
    return names.module(module, kind)


def _module_worker_ids(module: str) -> list[str]:
    api_dir = PROJECT_ROOT / 'core' / 'api'
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from src.core.utils.celery.module_queues import read_module_workers

    specs = read_module_workers(PROJECT_ROOT / 'modules' / module)
    return [str(spec['name']) for spec in specs if spec.get('name')]


def _generic_worker_needed(module: str) -> bool:
    api_dir = PROJECT_ROOT / 'core' / 'api'
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from src.core.utils.celery.module_queues import generic_module_worker_needed

    return generic_module_worker_needed(module, PROJECT_ROOT / 'modules' / module)


def _worker_service_ids(module: str, *, include_idle_generic: bool) -> list[str]:
    named = _module_worker_ids(module)
    if include_idle_generic or _generic_worker_needed(module):
        return ['', *named]
    return list(named)


def _write_wrappers(module: str, kind: str, worker_id: str = '') -> tuple[Path, Path]:
    ensure_dir(WRAPPERS)
    safe = _safe(module)
    suffix = f'{kind}_{_safe(worker_id)}' if kind == 'worker' and worker_id else kind
    bat = WRAPPERS / f'start_module_{safe}_{suffix}.bat'
    sh_path = WRAPPERS / f'start_module_{safe}_{suffix}.sh'
    py = PROJECT_ROOT / 'virtual_env' / 'python'
    if kind == 'api':
        script = 'core\\api\\scripts\\start_module_api.py' if os.name == 'nt' else 'core/api/scripts/start_module_api.py'
        extra = f'--module={module}'
    elif kind == 'beat':
        script = 'core\\api\\scripts\\start_celery_beat.py' if os.name == 'nt' else 'core/api/scripts/start_celery_beat.py'
        extra = f'--module={module}'
    else:
        script = 'core\\api\\scripts\\start_celery_worker.py' if os.name == 'nt' else 'core/api/scripts/start_celery_worker.py'
        extra = f'--module={module}'
        if worker_id:
            extra = f'{extra} --worker={worker_id}'
    bat.write_text(
        '@echo off\r\n'
        f'cd /d "{PROJECT_ROOT}"\r\n'
        f'"{py / "Scripts" / "python.exe"}" {script} {extra}\r\n',
        encoding='utf-8',
    )
    write_sh(
        sh_path,
        '#!/usr/bin/env bash\n'
        'set -euo pipefail\n'
        f'cd "{PROJECT_ROOT}"\n'
        f'"{py / "bin" / "python"}" {script.replace(chr(92), "/")} {extra}\n',
    )
    return bat, sh_path


def _write_systemd_unit(module: str, kind: str, sh_path: Path, worker_id: str = '') -> Path:
    unit_dir = WRAPPERS / 'systemd'
    ensure_dir(unit_dir)
    name = _service_name(module, kind, worker_id)
    label = f'{kind} {worker_id}'.strip() if worker_id else kind
    unit = unit_dir / f'{name}.service'
    stderr = PROJECT_ROOT / 'logs' / f'{name}.stderr.log'
    env_file = WRAPPERS / 'ergo_ms.env'
    stop_post = ''
    if kind == 'worker':
        # SIGKILL по TimeoutStopSec не даёт Celery вернуть задачу. Это делает скрипт,
        # когда процесса уже нет и новый ещё не поднялся (RestartSec).
        stop_post = (
            f'ExecStopPost={PROJECT_ROOT}/virtual_env/python/bin/python '
            f'{PROJECT_ROOT}/core/deployment/scripts/celery_requeue_unacked.py --quiet\n'
        )
    content = (
        '[Unit]\n'
        f'Description=ERGO MS module {label} ({module})\n'
        'After=network.target\n'
        '\n'
        '[Service]\n'
        'Type=simple\n'
        f'EnvironmentFile=-{env_file}\n'
        f'ExecStart=/bin/bash "{sh_path}"\n'
        'Restart=always\n'
        'RestartSec=5\n'
        'TimeoutStopSec=30\n'
        f'{stop_post}'
        'Environment=PYTHONUNBUFFERED=1\n'
        'Environment=ERGO_LOG_CONSOLE=false\n'
        'StandardOutput=null\n'
        f'StandardError=append:{stderr}\n'
        '\n'
        '[Install]\n'
        'WantedBy=multi-user.target\n'
    )
    unit.write_text(content, encoding='utf-8')
    return unit


def _install_linux(module: str, kind: str, sh_path: Path, worker_id: str = '') -> int:
    unit = _write_systemd_unit(module, kind, sh_path, worker_id)
    name = _service_name(module, kind, worker_id)
    print(format_console('info', t('module_service_unit_written', path=unit)))
    link = subprocess.call(['systemctl', 'link', str(unit)])
    if link != 0:
        print(format_console('warning', t('module_service_systemctl_hint', unit=name)))
        return 0
    subprocess.call(['systemctl', 'enable', '--now', name])
    return 0


def _nssm_exe() -> Path | None:
    candidate = PROJECT_ROOT / 'virtual_env' / 'packages' / 'nssm' / 'win64' / 'nssm.exe'
    if candidate.is_file():
        return candidate
    alt = PROJECT_ROOT / 'virtual_env' / 'packages' / 'nssm' / 'nssm.exe'
    return alt if alt.is_file() else None


def _install_windows(module: str, kind: str, bat: Path, worker_id: str = '') -> int:
    nssm = _nssm_exe()
    name = _service_name(module, kind, worker_id)
    if nssm is None:
        print(format_console('warning', t('module_service_nssm_missing', wrapper=bat, name=name)))
        return 0
    subprocess.call([str(nssm), 'install', name, str(bat)])
    subprocess.call([str(nssm), 'set', name, 'AppDirectory', str(PROJECT_ROOT)])
    subprocess.call([str(nssm), 'start', name])
    print(format_console('ok', t('module_service_installed', name=name)))
    return 0


def _windows_service_exists(name: str) -> bool:
    result = subprocess.run(['sc', 'query', name], capture_output=True, check=False)
    return result.returncode == 0


def _linux_unit_exists(name: str) -> bool:
    unit = name if name.endswith('.service') else f'{name}.service'
    path = Path('/etc/systemd/system') / unit
    if path.is_file() or path.is_symlink():
        return True
    result = subprocess.run(
        ['systemctl', 'list-unit-files', '--type=service', '--no-legend', unit],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool((result.stdout or '').strip())


def _uninstall_windows(name: str) -> int:
    if not _windows_service_exists(name):
        return 0
    nssm = _nssm_exe()
    if nssm is None:
        print(format_console('skip', t('module_service_nssm_missing', wrapper='-', name=name)))
        return 0
    subprocess.call([str(nssm), 'stop', name])
    subprocess.call([str(nssm), 'remove', name, 'confirm'])
    return 0


def _uninstall_linux(name: str) -> int:
    if not _linux_unit_exists(name):
        return 0
    subprocess.call(['systemctl', 'disable', '--now', name])
    return 0


def main() -> int:
    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description='Install or remove a module OS service')
    parser.add_argument('--module', required=True)
    parser.add_argument('--kind', choices=('api', 'worker', 'beat'), default='api')
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    module = args.module.strip()
    kind = args.kind
    if not (PROJECT_ROOT / 'modules' / module).is_dir():
        print(format_console('error', t('module_service_unknown_module', name=module)), file=sys.stderr)
        return 2
    if kind != 'worker':
        worker_ids = ['']
    elif args.uninstall:
        worker_ids = _worker_service_ids(module, include_idle_generic=True)
    else:
        worker_ids = _worker_service_ids(module, include_idle_generic=False)
    if args.uninstall:
        code = 0
        for worker_id in worker_ids:
            name = _service_name(module, kind, worker_id)
            if os.name == 'nt':
                code = _uninstall_windows(name) or code
            else:
                code = _uninstall_linux(name) or code
        return code
    if kind == 'worker' and not _generic_worker_needed(module):
        idle_name = _service_name(module, 'worker', '')
        if os.name == 'nt':
            _uninstall_windows(idle_name)
        else:
            _uninstall_linux(idle_name)
    from lifecycle.modules.catalog import ModuleCatalog  # noqa: WPS433

    catalog = ModuleCatalog.from_project_env(PROJECT_ROOT)
    if not catalog.allows_module_process_os_services(module):
        print(format_console('skip', t('module_process_service_skip_runtime', name=module)))
        return 0
    code = 0
    for worker_id in worker_ids:
        bat, sh_path = _write_wrappers(module, kind, worker_id)
        if os.name == 'nt':
            code = _install_windows(module, kind, bat, worker_id) or code
        else:
            code = _install_linux(module, kind, sh_path, worker_id) or code
    return code


if __name__ == '__main__':
    raise SystemExit(main())
