from __future__ import annotations

import io
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

import _bootstrap  # noqa: F401


ROOT = Path(__file__).resolve().parents[3]
DEPLOYMENT = ROOT / 'core/deployment'
DISPATCH = DEPLOYMENT / 'lifecycle/host/internal_dispatch.sh'


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('bash'), 'Linux bash required')
class PortableRuntimeBootstrapTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'virtual_env/cache/tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base, prefix='runtime bootstrap ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def executable(self, relative, source):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
        path.chmod(0o755)
        return path

    def dispatch(self, operation, *, env=None):
        return subprocess.run(
            ['bash', str(DISPATCH), 'runtime', operation, str(self.root)],
            capture_output=True, text=True, timeout=30, env=env,
        )

    def test_ready_runtimes_succeed_before_project_python_exists(self):
        for operation, relative in (
            ('install-nodejs', 'virtual_env/packages/nodejs/bin/node'),
            ('install-python', 'virtual_env/packages/python/bin/python3'),
        ):
            with self.subTest(operation=operation):
                binary = self.executable(relative, '#!/bin/sh\necho bootstrap-runtime\n')
                before = binary.read_bytes(), binary.stat().st_mtime_ns
                result = self.dispatch(operation)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((binary.read_bytes(), binary.stat().st_mtime_ns), before)
                binary.unlink()
        self.assertFalse((self.root / 'virtual_env/python').exists())

    def test_node_installs_from_cache_before_project_python_exists(self):
        machine = platform.machine().lower()
        architecture = {'x86_64': 'linux-x64', 'amd64': 'linux-x64', 'aarch64': 'linux-arm64', 'arm64': 'linux-arm64'}.get(machine)
        if architecture is None:
            self.skipTest('Unsupported portable Node architecture')
        script = (DEPLOYMENT / 'linux/lib/portable_nodejs.sh').read_text(encoding='utf-8')
        version = re.search(r"^PORTABLE_NODE_LTS_VERSION='([^']+)'", script, re.MULTILINE).group(1)
        folder = f'node-v{version}-{architecture}'
        archive = self.root / 'virtual_env/cache/downloads' / (folder + '.tar.xz')
        archive.parent.mkdir(parents=True)
        payload = b'#!/bin/sh\necho bootstrap-runtime\n'
        with tarfile.open(archive, 'w:xz') as output:
            entry = tarfile.TarInfo(folder + '/bin/node')
            entry.size = len(payload)
            entry.mode = 0o755
            output.addfile(entry, io.BytesIO(payload))
        before = archive.read_bytes(), archive.stat().st_mtime_ns
        result = self.dispatch('install-nodejs')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / 'virtual_env/packages/nodejs/bin/node').read_bytes(), payload)
        self.assertEqual((archive.read_bytes(), archive.stat().st_mtime_ns), before)
        self.assertFalse((self.root / 'virtual_env/python').exists())

    def test_real_download_failure_still_stops_bootstrap(self):
        curl = self.executable('commands/curl', '#!/bin/sh\necho attempted > "$ERGO_TEST_CURL_CALLED"\nexit 7\n')
        called = self.root / 'curl-called'
        environment = {
            **os.environ,
            'PATH': str(curl.parent) + os.pathsep + os.environ['PATH'],
            'ERGO_TEST_CURL_CALLED': str(called),
        }
        result = self.dispatch('install-nodejs', env=environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(called.is_file(), result.stdout + result.stderr)
        self.assertFalse((self.root / 'virtual_env/packages/nodejs/bin/node').exists())


if __name__ == '__main__':
    unittest.main()
