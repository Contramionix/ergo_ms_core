"""След выкладки: версии submodule и снимок баз перед миграцией."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_DEPLOYMENT_DIR = Path(__file__).resolve().parents[2]
if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))

from cli_locale import t  # noqa: E402
from console_tags import format_console  # noqa: E402

from lifecycle.context import DeploymentContext  # noqa: E402
from lifecycle.host import ops as host_ops  # noqa: E402
from lifecycle.steps.base import DeploymentStep, StepResult  # noqa: E402


def git_head(path: Path) -> str:
    if not path.is_dir():
        return ''
    result = subprocess.run(
        ['git', '-C', str(path), 'rev-parse', 'HEAD'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    if result.returncode != 0:
        return ''
    return result.stdout.strip()


def write_deploy_revision(root: Path, paths: tuple[str, ...], dest: Path) -> bool:
    """Пишет SHA корня и перечисленных submodule. Пустая строка SHA — ошибка."""
    lines: list[str] = []
    root_sha = git_head(root)
    if not root_sha:
        return False
    lines.append(f'root {root_sha}')
    for rel in paths:
        sha = git_head(root / rel)
        if not sha:
            return False
        lines.append(f'{rel} {sha}')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return True


class RecordDeployRevisionStep(DeploymentStep):
    def __init__(self, paths: tuple[str, ...]) -> None:
        self.paths = paths

    @property
    def name(self) -> str:
        return 'record_deploy_revision'

    def run(self, ctx: DeploymentContext) -> StepResult:
        from log_env import resolve_logs_dir

        dest = resolve_logs_dir(ctx.project_root) / 'deploy-revision.txt'
        if not write_deploy_revision(ctx.project_root, self.paths, dest):
            print(format_console('error', t('deploy_revision_failed')), file=sys.stderr)
            return StepResult(exit_code=1, message=t('deploy_revision_failed'))
        try:
            shown = dest.relative_to(ctx.project_root).as_posix()
        except ValueError:
            shown = str(dest)
        print(format_console('ok', t('deploy_revision_written', path=shown)))
        return StepResult()


class BackupDatabaseStep(DeploymentStep):
    @property
    def name(self) -> str:
        return 'backup_database'

    def run(self, ctx: DeploymentContext) -> StepResult:
        print(format_console('info', t('deploy_backup_start')))
        code = host_ops.run_python_script(
            ctx,
            'core/deployment/scripts/backup_database.py',
        )
        return StepResult(exit_code=code)
