"""Foreground dev-процессы."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_DEPLOYMENT_DIR = Path(__file__).resolve().parents[2]
if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))

from cli_locale import t  # noqa: E402
from lifecycle.context import DeploymentContext  # noqa: E402
from lifecycle.host import ops as host_ops  # noqa: E402
from lifecycle.steps.base import DeploymentStep, StepResult  # noqa: E402

# Совпадает с core/api/.../startup_timing (без импорта API из deployment).
_API_START_WALL_ENV = 'ERGO_API_START_WALL'
_MEDIA_START_WALL_ENV = 'ERGO_MEDIA_API_START_WALL'

_DEV_SCRIPTS = {
    'dev-api': [
        'core/api/scripts/warmup_caches_if_needed.py',
        'core/api/scripts/start_api.py',
    ],
    'dev-client': ['core/deployment/scripts/start_client_if_dev.py'],
    'dev-client-enabled': ['core/deployment/scripts/start_client_if_enabled.py'],
    'dev-media': ['core/api/scripts/start_media_api.py'],
    'dev-beat': ['core/api/scripts/start_celery_beat.py'],
    'dev-jupyter': ['core/api/scripts/start_jupyter.py'],
    'warmup-caches-if-needed': ['core/api/scripts/warmup_caches_if_needed.py'],
    'sync-logs-services': ['core/deployment/scripts/sync_vscode_logs_services.py'],
}


class DevForegroundStep(DeploymentStep):
    def __init__(self, recipe_key: str) -> None:
        self._recipe_key = recipe_key

    @property
    def name(self) -> str:
        return f'dev_{self._recipe_key}'

    def should_run(self, ctx: DeploymentContext) -> bool:
        return ctx.runtime == 'host'

    def run(self, ctx: DeploymentContext) -> StepResult:
        scripts = list(_DEV_SCRIPTS.get(self._recipe_key, []))
        if not scripts:
            return StepResult(exit_code=1, message=t('unknown_dev_recipe', name=self._recipe_key))
        if self._recipe_key == 'dev-api' and os.environ.get('ERGO_WARMUP_DONE', '').strip().lower() in (
            '1',
            'true',
            'yes',
        ):
            scripts = [rel for rel in scripts if not rel.endswith('warmup_caches_if_needed.py')]
        # Wall-clock до warmup/скрипта — итог включает всю цепочку рецепта.
        if self._recipe_key == 'dev-api':
            os.environ.setdefault(_API_START_WALL_ENV, str(time.time()))
        elif self._recipe_key == 'dev-media':
            os.environ.setdefault(_MEDIA_START_WALL_ENV, str(time.time()))
        script_args: list[str] = []
        if self._recipe_key in ('sync-logs-services', 'dev-beat'):
            # start-beat --module=<name> и sync-logs-services --json → runner parse_known_args
            script_args = [str(a) for a in (ctx.options.get('compose_extra_args') or [])]
        code = 0
        for rel in scripts:
            code = host_ops.run_python_script(
                ctx, rel, prefer_venv=True, script_args=script_args
            )
            if code != 0:
                return StepResult(exit_code=code)
        return StepResult()


def _flag_value(args: list[str], name: str) -> str:
    prefix = f'--{name}='
    for index, arg in enumerate(args):
        if arg.startswith(prefix):
            return arg[len(prefix):].strip()
        if arg == f'--{name}' and index + 1 < len(args):
            return str(args[index + 1]).strip()
    return ''


def _named_module_workers(ctx: DeploymentContext, module: str) -> list[dict]:
    """Имена воркеров из hook. Читает их venv-скрипт, не процесс runner."""
    if not module:
        return []
    script = ctx.project_root / 'core/api/scripts/start_celery_worker.py'
    py = host_ops.pick_python_for_ctx(ctx)
    result = subprocess.run(
        [*py, str(script), '--module', module, '--list-module-workers'],
        cwd=str(ctx.project_root),
        env=host_ops.api_env(ctx),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    try:
        payload = json.loads(result.stdout or '[]')
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict) and item.get('name')]


class DevWorkerStep(DeploymentStep):
    @property
    def name(self) -> str:
        return 'dev_worker'

    def run(self, ctx: DeploymentContext) -> StepResult:
        extra = [str(a) for a in (ctx.options.get('compose_extra_args') or [])]
        script = 'core/api/scripts/start_celery_worker.py'
        py = host_ops.pick_python_for_ctx(ctx)
        script_path = ctx.project_root / script
        cmd = [*py, str(script_path)]
        extra_has_module = any(a == '--module' or a.startswith('--module=') for a in extra)
        extra_has_worker = any(a == '--worker' or a.startswith('--worker=') for a in extra)
        worker = ctx.option_str('worker', '')
        if extra_has_module:
            pass
        elif extra_has_worker:
            pass
        elif worker:
            cmd.extend(['--worker', worker])
        else:
            cmd.extend(['--worker', 'all'])
        cmd.extend(extra)
        named: list[subprocess.Popen] = []
        if extra_has_module and not extra_has_worker:
            module = _flag_value(extra, 'module')
            env = host_ops.api_env(ctx)
            for spec in _named_module_workers(ctx, module):
                worker_id = str(spec['name'])
                named.append(subprocess.Popen(
                    [*py, str(script_path), '--module', module, '--worker', worker_id],
                    cwd=str(ctx.project_root),
                    env=env,
                    start_new_session=True,
                ))
        interrupted = False
        try:
            code = subprocess.call(
                cmd,
                cwd=str(ctx.project_root),
                env=host_ops.api_env(ctx),
            )
        except KeyboardInterrupt:
            interrupted = True
            code = 130
        if interrupted:
            for proc in named:
                if proc.poll() is None:
                    proc.terminate()
        return StepResult(exit_code=code)
