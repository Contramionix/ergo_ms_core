"""npm must receive semver ranges intact on Windows and Linux."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import _bootstrap  # noqa: F401

from project_layout import npm_exe  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


class NpmArgumentTests(unittest.TestCase):
    def test_semver_range_uses_all_matching_versions_from_local_registry(self):
        node = npm_exe(ROOT).parent / ('node.exe' if os.name == 'nt' else 'node')
        if not node.is_file():
            self.skipTest('Portable Node.js is required')
        versions = {'1.0.0': {'name': 'fixture-package', 'version': '1.0.0'},
                    '1.1.0': {'name': 'fixture-package', 'version': '1.1.0'}}
        payload = json.dumps({'name': 'fixture-package', 'versions': versions,
                              'dist-tags': {'latest': '1.1.0'}}).encode()

        class Registry(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                return

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, ThreadingHTTPServer(('127.0.0.1', 0), Registry) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                folder = Path(tmp)
                for filename in ('user.npmrc', 'global.npmrc'):
                    (folder / filename).write_text('', encoding='utf-8')
                environment = {**os.environ,
                               'PATH': str(node.parent) + os.pathsep + os.environ.get('PATH', ''),
                               'NO_PROXY': 'localhost,127.0.0.1', 'no_proxy': 'localhost,127.0.0.1',
                               'npm_config_cache': str(folder / 'cache'), 'npm_config_offline': 'false',
                               'npm_config_fund': 'false', 'npm_config_audit': 'false',
                               'npm_config_userconfig': str(folder / 'user.npmrc'),
                               'npm_config_globalconfig': str(folder / 'global.npmrc')}
                script = (ROOT / 'core/deployment/scripts/run_npm_spawn.js').as_uri()
                args = ['view', 'fixture-package@^1.0.0', 'version', '--json',
                        '--registry', f'http://127.0.0.1:{server.server_port}',
                        '--fetch-timeout=10000', '--fetch-retries=0', '--update-notifier=false']
                code = (f'import {{runNpm}} from {json.dumps(script)};'
                        f'const result=runNpm({json.dumps(args)},{{stdio:"pipe",encoding:"utf8"}});'
                        'process.stdout.write(result.stdout || "");'
                        'process.stderr.write(result.stderr || "");process.exit(result.status ?? 1)')
                # Под параллельным ergoms ci старт npm занимает десятки секунд.
                # Таймаут subprocess.run процесс не убивает, и каталог остаётся занят.
                proc = subprocess.Popen(
                    [str(node), '--input-type=module', '-e', code],
                    cwd=folder,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    stdout, stderr = proc.communicate(timeout=90)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                    self.fail('npm view не завершился за 90 с')
                self.assertEqual(proc.returncode, 0, stderr)
                self.assertEqual(json.loads(stdout), ['1.0.0', '1.1.0'])
            finally:
                server.shutdown()
                thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
