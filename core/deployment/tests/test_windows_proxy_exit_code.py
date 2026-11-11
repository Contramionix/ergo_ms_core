"""PowerShell -File must preserve failures from the public proxy commands."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import venv


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell is required')
class WindowsProxyExitCodeTests(unittest.TestCase):
    def test_proxy_commands_preserve_success_and_failure_exit_codes(self):
        powershell = shutil.which('powershell.exe')
        if powershell is None:
            self.skipTest('Windows PowerShell is unavailable')
        script = Path(__file__).resolve().parents[1] / 'windows/ergo_ms.ps1'
        with tempfile.TemporaryDirectory(prefix='ergoms_proxy_') as tmp:
            root = Path(tmp)
            virtualenv = root / 'virtual_env/python'
            venv.EnvBuilder(with_pip=False).create(virtualenv)
            api = root / 'core/api/commands'
            media = root / 'core/media_api/src/media_server'
            for directory in (api, media):
                directory.mkdir(parents=True)
                (directory / '__init__.py').write_text('', encoding='utf-8')
            stub = 'import sys; raise SystemExit(int(sys.argv[-1]))\n'
            (api / '__main__.py').write_text(stub, encoding='utf-8')
            (media / 'manage.py').write_text(stub, encoding='utf-8')
            (virtualenv / 'Scripts/poetry.cmd').write_text('@exit /b %1\n', encoding='ascii')
            allowed = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE',
                       'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
                       'PROGRAMDATA', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'USERNAME', 'USERDOMAIN'}
            environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
            environment.update(TEMP=tmp, TMP=tmp, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
            for command in ('api', 'media_api', 'poetry'):
                for code in (0, 7):
                    with self.subTest(command=command, code=code):
                        result = subprocess.run(
                            [powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                             '-Root', str(root), '-Command', command, str(code)],
                            cwd=root, env=environment, capture_output=True, text=True,
                            encoding='utf-8', timeout=45,
                        )
                        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
