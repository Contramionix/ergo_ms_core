from __future__ import annotations

import ctypes
import os
import subprocess
import unittest
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_CLI = _PROJECT_ROOT / 'core' / 'deployment' / 'bin' / 'ergoms.cmd'


@unittest.skipUnless(os.name == 'nt', 'Windows CLI regression tests')
class WindowsCliAccessTests(unittest.TestCase):
    def _run_cli(self, command: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [os.environ.get('COMSPEC', 'cmd.exe'), '/c', str(_LOCAL_CLI), command],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            timeout=60,
        )

    def test_help_runs_without_administrator(self) -> None:
        result = self._run_cli('help')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('ergoms', result.stdout.lower())

    def test_service_start_still_requires_administrator(self) -> None:
        if ctypes.windll.shell32.IsUserAnAdmin():
            self.skipTest('Service start must only be tested without elevation')
        result = self._run_cli('start')
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertNotIn('ScriptRequiresElevation', output)
        self.assertIn('[ERROR]', output)
        self.assertIn('start', output)


if __name__ == '__main__':
    unittest.main()
