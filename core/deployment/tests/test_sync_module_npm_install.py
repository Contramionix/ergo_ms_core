"""Offline npm regression: staging must preserve the core dependency graph."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

import _bootstrap  # noqa: F401

from project_layout import npm_exe  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = 'core/deployment/scripts/sync-module-npm-deps.js'
FILES = (
    SCRIPT,
    'core/deployment/scripts/sync-module-npm-tree.js',
    'core/deployment/scripts/run_npm_spawn.js',
    'core/client/scripts/lib/parse-disabled-modules.js',
    'core/client/scripts/lib/module-env.js',
)


class SyncModuleNpmInstallTests(unittest.TestCase):
    def test_module_install_preserves_core_transitives_and_repeat_is_offline(self):
        npm = npm_exe(PROJECT_ROOT)
        node = npm.parent / ('node.exe' if os.name == 'nt' else 'node')
        if not node.is_file():
            self.skipTest('Portable Node.js is required for the offline npm integration test')

        for module_name in ('module-entry', '@fixture/module-entry'):
            with self.subTest(module_name=module_name), tempfile.TemporaryDirectory(prefix='npm staging ') as tmp:
                root = Path(tmp)
                for relative in FILES:
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(PROJECT_ROOT / relative, target)
                (root / 'package.json').write_text('{"type":"module"}', encoding='utf-8')
                npm_root = root / 'virtual_env/npm'
                npm_root.mkdir(parents=True)

                def package(name, version, files, dependencies=None, exports=None):
                    archive = root / (name.replace('/', '-') + '-' + version + '.tgz')
                    manifest = {'name': name, 'version': version, 'main': 'index.cjs'}
                    if dependencies:
                        manifest['dependencies'] = dependencies
                    if exports:
                        manifest['exports'] = exports
                    with tarfile.open(archive, 'w:gz') as stream:
                        for filename, value in {'package.json': json.dumps(manifest), **files}.items():
                            data = value.encode('utf-8')
                            member = tarfile.TarInfo('package/' + filename)
                            member.size = len(data)
                            stream.addfile(member, io.BytesIO(data))
                    return 'file:' + archive.as_posix()

                old = package('shared', '1.0.0', {'index.cjs': "module.exports = 'module'"},
                              exports={'.': './index.cjs'})
                new = package('shared', '2.0.0', {'decode.cjs': "module.exports = 'core'"},
                              exports={'./decode': './decode.cjs'})
                core = package('core-entry', '1.0.0', {'index.cjs': "module.exports = require('shared/decode')"},
                               {'shared': new})
                module = package(module_name, '1.0.0', {'index.cjs': "module.exports = require('shared')"},
                                 {'shared': old})
                manifest = {'name': 'fixture', 'private': True, 'dependencies': {'core-entry': core}}
                (npm_root / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
                environment = {**os.environ, 'PATH': str(node.parent) + os.pathsep + os.environ.get('PATH', ''),
                               'DISABLED_MODULES': '', 'npm_config_offline': 'true',
                               'npm_config_registry': 'http://127.0.0.1:9',
                               'npm_config_cache': str(root / 'virtual_env/cache/npm')}

                def run(*args):
                    result = subprocess.run([str(node), *args], cwd=root, env=environment,
                                            capture_output=True, text=True, timeout=90)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    return result.stdout

                # A real local-only lock, kept unchanged by both install:all calls.
                spawn = (root / 'core/deployment/scripts/run_npm_spawn.js').as_uri()
                run('--input-type=module', '-e',
                    f'import {{runNpm}} from {json.dumps(spawn)};'
                    'const result=runNpm(["install","--package-lock-only","--ignore-scripts",'
                    '"--no-audit","--no-fund"],{cwd:"virtual_env/npm"});'
                    'process.exit(result.status ?? 1)')
                lock = (npm_root / 'package-lock.json').read_bytes()
                run(SCRIPT, '--install-all')
                shared = npm_root / 'node_modules/shared/package.json'
                core_shared = shared.read_bytes()
                consumer = root / 'modules/consumer/client'
                consumer.mkdir(parents=True)
                (consumer / 'package.json').write_text(json.dumps({'dependencies': {module_name: module}}),
                                                      encoding='utf-8')

                run(SCRIPT, '--install-all')
                self.assertEqual(shared.read_bytes(), core_shared, 'Module staging replaced a core transitive')
                require = (
                    'const {createRequire}=require("node:module");'
                    'const r=createRequire(process.cwd()+"/virtual_env/npm/package.json");'
                    f'console.log(JSON.stringify([r("core-entry"),r({json.dumps(module_name)})]));'
                )
                self.assertEqual(json.loads(run('-e', require)), ['core', 'module'])
                self.assertEqual((npm_root / 'package-lock.json').read_bytes(), lock)
                # A directory left by an interrupted install must not count as
                # a usable dependency. Repair it without replacing core packages.
                module_manifest = npm_root / 'node_modules' / module_name / 'package.json'
                module_manifest.unlink()
                check = subprocess.run([str(node), SCRIPT, '--check'], cwd=root, env=environment,
                                       capture_output=True, text=True, timeout=90)
                self.assertEqual(check.returncode, 1, check.stdout + check.stderr)
                run(SCRIPT, '--install-all')
                self.assertTrue(module_manifest.is_file())
                self.assertEqual(shared.read_bytes(), core_shared)
                self.assertEqual(json.loads(run('-e', require)), ['core', 'module'])
                self.assertEqual((npm_root / 'package-lock.json').read_bytes(), lock)
                before = {p.relative_to(npm_root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
                          for p in (npm_root / 'node_modules').rglob('*')
                          if p.is_file() and not p.name.startswith('.ergo-')}
                output = run(SCRIPT, '--install-all')
                after = {p.relative_to(npm_root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
                         for p in (npm_root / 'node_modules').rglob('*')
                         if p.is_file() and not p.name.startswith('.ergo-')}
                self.assertEqual(before, after)
                self.assertNotIn('staging (', output)
                self.assertEqual((npm_root / 'package-lock.json').read_bytes(), lock)


if __name__ == '__main__':
    unittest.main()
