"""Verify required local models after the existing provider setup tasks."""

from pathlib import Path
import subprocess

from lifecycle.host import ops as host_ops
from lifecycle.docker import ops as docker_ops
from lifecycle.steps.base import DeploymentStep, StepResult


class VerifyRequiredModelsStep(DeploymentStep):
    @property
    def name(self):
        return 'verify_required_models'

    def should_run(self, ctx):
        return ctx.runtime == 'host'

    def run(self, ctx):
        if not host_ops.venv_exists(ctx.project_root, ctx.platform):
            return StepResult(exit_code=1, message='Для проверки моделей необходимо окружение Python')
        command = [str(host_ops.venv_python_exe(ctx.project_root, ctx.platform)),
                   str(Path(__file__).resolve().parents[2] / 'model_index/cli.py'),
                   'check', '--root', str(ctx.project_root)]
        code = subprocess.call(command, cwd=ctx.project_root, env={**host_ops.api_env(ctx), **ctx.raw_env})
        return StepResult(exit_code=code)


class InstallRuntimeModelsStep(DeploymentStep):
    @property
    def name(self):
        return 'install_runtime_models'

    def should_run(self, ctx):
        return ctx.runtime == 'docker'

    def run(self, ctx):
        shell = ('cd /app/core/api && PYTHONPATH=/app/core/api:/app poetry run python '
                 '/app/core/deployment/model_index/cli.py install --root /app')
        return StepResult(exit_code=docker_ops.run_api_oneoff(shell, mode=ctx.docker_mode,
                          skip_infra_wait=True, project_root=ctx.project_root))
