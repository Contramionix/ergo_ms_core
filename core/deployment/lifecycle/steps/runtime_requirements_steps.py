"""Runtime tools use the existing package installer, after Python bootstrap."""

from __future__ import annotations

import subprocess
from pathlib import Path

from lifecycle.host import ops as host_ops
from ergo_modes import env_bool_key
from lifecycle.docker import ops as docker_ops
from lifecycle.steps.base import DeploymentStep, StepResult


class RuntimeRequirementsStep(DeploymentStep):
    @property
    def name(self):
        return 'runtime_requirements'

    def run(self, ctx):
        if not host_ops.venv_exists(ctx.project_root, ctx.platform):
            return StepResult(exit_code=1, message='Для runtime-инструментов необходимо окружение Python')
        venv_python = str(host_ops.venv_python_exe(ctx.project_root, ctx.platform))
        environment = {**host_ops.api_env(ctx), **ctx.raw_env}
        # Compose запускает хост (docker_ops на машине), поэтому ставится на хост и в docker-режиме тоже.
        if env_bool_key(ctx.raw_env, 'DOCKER_COMPOSE_INSTALL_PORTABLE'):
            installer = Path(__file__).resolve().parents[2] / 'packages' / 'installers' / 'docker_compose.py'
            code = subprocess.call([venv_python, str(installer), '--root', str(ctx.project_root)], cwd=str(ctx.project_root), env=environment)
            if code != 0:
                return StepResult(exit_code=code)
        if ctx.runtime == 'docker':
            shell = (
                'cd /app/core/api && '
                'PYTHONPATH=/app/core/api:/app poetry run python '
                '/app/core/deployment/packages/cli.py --root /app install-required'
            )
            return StepResult(exit_code=docker_ops.run_api_oneoff(shell, mode=ctx.docker_mode, skip_infra_wait=True, project_root=ctx.project_root))
        script = Path(__file__).resolve().parents[2] / 'packages' / 'cli.py'
        command = [venv_python, str(script), '--root', str(ctx.project_root), 'install-required']
        code = subprocess.call(command, cwd=str(ctx.project_root), env=environment)
        return StepResult(exit_code=code)
