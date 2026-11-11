from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from lifecycle.steps.deploy_trace import write_deploy_revision  # noqa: E402


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ['git', '-c', 'user.email=ergo@example.com', '-c', 'user.name=ergo', *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


class DeployRevisionTests(unittest.TestCase):
    def test_writes_root_and_nested_heads(self) -> None:
        if shutil.which('git') is None:
            self.skipTest('git не найден')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, 'init')
            (root / 'readme.txt').write_text('root', encoding='utf-8')
            _git(root, 'add', 'readme.txt')
            _git(root, 'commit', '-m', 'root')
            nested = root / 'core' / 'api'
            nested.mkdir(parents=True)
            _git(nested, 'init')
            (nested / 'a.txt').write_text('api', encoding='utf-8')
            _git(nested, 'add', 'a.txt')
            _git(nested, 'commit', '-m', 'api')
            dest = root / 'logs' / 'deploy-revision.txt'
            self.assertTrue(write_deploy_revision(root, ('core/api',), dest))
            text = dest.read_text(encoding='utf-8')
            self.assertTrue(text.startswith('root '))
            self.assertIn('\ncore/api ', text)

    def test_missing_repository_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / 'logs' / 'deploy-revision.txt'
            self.assertFalse(write_deploy_revision(root, (), dest))
            self.assertFalse(dest.exists())


if __name__ == '__main__':
    unittest.main()
