from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import _bootstrap  # noqa: F401

from packages.installer import _run_custom_installer, is_installed, is_platform_supported
from packages.archive import ArchiveInstallError
from packages.installers import chrome, libreoffice, ollama, tesseract
from packages.registry import get_package

ROOT = Path(__file__).resolve().parents[3]


class CommonToolInstallerTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'virtual_env/cache/tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base, prefix='test_tools_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def file(self, relative, payload=None):
        path = self.root / 'virtual_env/packages' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload or os.urandom(2048))
        return path

    def test_legacy_installer_imports_preserve_helpers_and_patch_targets(self):
        found = set()
        for path in (ROOT / 'modules').glob('*/deployment/install_*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            tool_imports = [node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == 'packages.installers']
            if not tool_imports:
                continue
            name = tool_imports[0].names[0].name
            module_name = '.'.join(path.relative_to(ROOT).with_suffix('').parts)
            code = (
                'import sys,importlib;sys.path[:0]=sys.argv[1:3];'
                'legacy=importlib.import_module(sys.argv[3]);'
                'shared=importlib.import_module(sys.argv[4]);'
                'assert legacy is shared;assert legacy.main is shared.main'
            )
            result = subprocess.run([sys.executable, '-c', code, str(ROOT), str(ROOT / 'core/deployment'), module_name, f'packages.installers.{name}'], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            found.add(name)
        if not found:
            self.skipTest('Legacy installer adapters are not present in this checkout')

    def test_readiness_and_supported_platforms_for_windows_and_linux(self):
        for platform in ('windows', 'linux'):
            for name in ('libreoffice', 'ollama', 'tesseract', 'chrome-for-testing'):
                spec = get_package(self.root, name)
                marker = spec.marker_windows if platform == 'windows' else spec.marker_linux
                self.file(f'{spec.dest}/{marker}')
                for alternatives in spec.required_files.get(platform, ()):
                    self.file(f'{spec.dest}/{alternatives[0]}')
                with self.subTest(platform=platform, name=name), patch('packages.installer.current_platform_key', return_value=platform):
                    self.assertTrue(is_platform_supported(spec))
                    self.assertTrue(is_installed(self.root, spec))
                with patch('packages.installer.current_platform_key', return_value='darwin'):
                    self.assertFalse(is_platform_supported(spec))

    def test_ready_tools_skip_downloads_and_linux_office_retains_library_check(self):
        self.file('libreoffice/program/soffice')
        with patch.object(libreoffice, 'sys', SimpleNamespace(platform='linux', stderr=sys.stderr)), patch.object(libreoffice, 'ensure_runtime_libs') as check, patch.object(libreoffice, 'download_archive') as download:
            libreoffice.install(self.root, force=False, refresh=False)
            check.assert_called_once()
            download.assert_not_called()
        self.file('ollama/ollama.exe')
        with patch.object(ollama.platform, 'system', return_value='Windows'), patch.object(ollama, 'download_tool_asset') as download:
            self.assertEqual(ollama.install_ollama(self.root), 0)
            download.assert_not_called()
        for name in ('tesseract.exe', 'tessdata/rus.traineddata', 'tessdata/eng.traineddata'):
            self.file(f'tesseract/{name}')
        with patch.object(tesseract, 'sys', SimpleNamespace(platform='win32', stderr=sys.stderr)), patch.object(tesseract, '_install_tessdata') as download:
            self.assertEqual(tesseract.install(self.root), 0)
            download.assert_not_called()

    def test_linux_office_downloads_debian_libraries_and_tries_t64_on_renamed_packages(self):
        libraries = {
            'libdbus-1.so.3': 'libdbus-1-3',
            'libgio-2.0.so.0': 'libglib2.0-0',
            'libgobject-2.0.so.0': 'libglib2.0-0',
            'libglib-2.0.so.0': 'libglib2.0-0',
            'libX11.so.6': 'libx11-6',
            'libcups.so.2': 'libcups2',
            'libpcre2-8.so.0': 'libpcre2-8-0',
        }
        for soname, package in libraries.items():
            with self.subTest(soname=soname):
                self.assertEqual(libreoffice._guess_package(soname), package)

        dest = self.root / 'libreoffice'
        work = self.root / 'work'
        downloads = []

        def download(argv, *, cwd, **kwargs):
            package = argv[-1]
            downloads.append(package)
            if package == 'libglib2.0-0':
                return SimpleNamespace(returncode=100)
            (Path(cwd) / f'{package}.deb').write_bytes(b'test-deb')
            return SimpleNamespace(returncode=0)

        with (
            patch.object(libreoffice, 'sys', SimpleNamespace(platform='linux')),
            patch.object(libreoffice, '_missing_shared_libs', side_effect=[list(libraries), []]),
            patch.object(libreoffice.subprocess, 'run', side_effect=download),
            patch.object(libreoffice, '_extract_deb') as extract,
        ):
            libreoffice.ensure_runtime_libs(dest, work=work)
        self.assertEqual(downloads.count('libglib2.0-0'), 1)
        self.assertEqual(downloads.count('libglib2.0-0t64'), 1)
        self.assertEqual(len(downloads), len(set(libraries.values())) + 1)
        self.assertTrue(extract.called)
        self.assertTrue(all(call.args[1] == dest / 'sysroot' for call in extract.call_args_list))

    def test_chrome_installs_both_archives_then_repeat_needs_no_metadata_or_download(self):
        urls = []
        for name in ('chrome', 'chromedriver'):
            archive = self.root / f'{name}.zip'
            with zipfile.ZipFile(archive, 'w') as writer:
                writer.writestr(f'{name}-win64/{name}.exe', os.urandom(4096))
            urls.append(archive.as_uri())
        with patch.object(chrome, 'sys', SimpleNamespace(platform='win32', stderr=sys.stderr)), patch.object(chrome, '_fetch_stable', return_value=('test-version', *urls)) as fetch:
            self.assertEqual(chrome.install(self.root), 0)
            before = chrome.chrome_binary(self.root).stat().st_mtime_ns
            for name in ('chrome', 'chromedriver'):
                (self.root / f'{name}.zip').unlink()
            self.assertEqual(chrome.install(self.root), 0)
            self.assertEqual(chrome.chrome_binary(self.root).stat().st_mtime_ns, before)
            fetch.assert_called_once()

    def test_chrome_failed_second_archive_preserves_the_installed_version(self):
        marker = self.file('chrome-for-testing/VERSION', b'previous-version')
        binary = self.file('chrome-for-testing/chrome/chrome.exe', b'previous-binary')
        self.file('chrome-for-testing/chromedriver/chromedriver.exe')
        archive = self.root / 'chrome.zip'
        with zipfile.ZipFile(archive, 'w') as writer:
            writer.writestr('chrome-win64/chrome.exe', os.urandom(4096))
        with patch.object(chrome, 'sys', SimpleNamespace(platform='win32', stderr=sys.stderr)), patch.object(chrome, '_fetch_stable', return_value=('next-version', archive.as_uri(), (self.root / 'missing.zip').as_uri())):
            self.assertEqual(chrome.install(self.root, force=True), 1)
        self.assertEqual(marker.read_bytes(), b'previous-version')
        self.assertEqual(binary.read_bytes(), b'previous-binary')

    def test_custom_installer_receives_existing_force_and_supported_refresh_flags(self):
        for name in ('libreoffice', 'ollama', 'tesseract', 'chrome-for-testing'):
            spec = get_package(self.root, name)
            script = ROOT / 'core/deployment' / spec.installer
            with self.subTest(name=name), patch('packages.installer._resolve_installer_script', return_value=script), patch('packages.installer.subprocess.run') as run:
                run.return_value.returncode = 0
                self.assertEqual(_run_custom_installer(self.root, spec, force=True, refresh=True), 0)
            argv = run.call_args.args[0]
            self.assertIn('--force', argv)
            self.assertIn('--refresh', argv)
            self.assertEqual(argv[argv.index('--root') + 1], str(self.root))

    def test_chrome_and_tesseract_cli_accept_force_with_refresh(self):
        (self.root / 'pyproject.toml').write_text('[tool.poetry]\n', encoding='utf-8')
        for installer in (chrome, tesseract):
            with self.subTest(installer=installer.__name__), patch.object(installer, 'install', return_value=0) as install:
                self.assertEqual(installer.main(['--root', str(self.root), '--force', '--refresh']), 0)
            install.assert_called_once_with(self.root, force=True, refresh=True)

    def test_truncated_tesseract_binary_is_not_ready_for_setup(self):
        from packages.installer import install_package

        self.file('tesseract/tesseract.exe', b'partial')
        for language in ('rus', 'eng'):
            self.file(f'tesseract/tessdata/{language}.traineddata')
        spec = get_package(self.root, 'tesseract')
        with patch('packages.installer.current_platform_key', return_value='windows'), patch('packages.installer._run_custom_installer', return_value=0) as run:
            self.assertFalse(is_installed(self.root, spec))
            self.assertEqual(install_package(self.root, 'tesseract'), 1)
            run.assert_called_once()

    def test_failed_tesseract_upgrade_keeps_the_previous_language_files(self):
        old = {}
        for name in ('tesseract.exe', 'tessdata/rus.traineddata', 'tessdata/eng.traineddata', 'VERSION'):
            path = self.file(f'tesseract/{name}')
            old[path] = path.read_bytes()
        def partial_language_update(dest, **kwargs):
            data = dest / 'tessdata'
            data.mkdir(parents=True, exist_ok=True)
            (data / 'rus.traineddata').write_bytes(b'new data')
            raise ArchiveInstallError('second language download failed')
        with patch.object(tesseract, 'sys', SimpleNamespace(platform='win32', stderr=sys.stderr)), patch.object(tesseract, 'install_binary', return_value=self.root / 'staged.exe'), patch.object(tesseract, '_install_tessdata', side_effect=partial_language_update):
            self.assertEqual(tesseract.install(self.root, force=True), 1)
        for path, previous in old.items():
            self.assertEqual(path.read_bytes(), previous)

    def test_windows_nsis_install_keeps_custom_and_downloaded_language_files(self):
        custom = self.file('tesseract/tessdata/custom.traineddata')
        previous_custom = custom.read_bytes()
        setup = self.file('cached-setup.exe')
        languages = {name: (name.encode() * 200) for name in ('rus.traineddata', 'eng.traineddata')}

        def extract(argv, **kwargs):
            extracted = Path(next(arg[2:] for arg in argv if arg.startswith('-o'))) / 'app'
            (extracted / 'tessdata/configs').mkdir(parents=True)
            (extracted / 'tesseract.exe').write_bytes(b'binary' * 300)
            (extracted / 'libtesseract.dll').write_bytes(b'library')
            (extracted / 'tessdata/eng.traineddata').write_bytes(b'bundled English' * 200)
            (extracted / 'tessdata/configs/pdf').write_bytes(b'config')
            return SimpleNamespace(returncode=0)

        def download(dest, **kwargs):
            (dest / 'tessdata').mkdir(exist_ok=True)
            for name, data in languages.items():
                (dest / 'tessdata' / name).write_bytes(data)

        with (
            patch.object(tesseract, 'sys', SimpleNamespace(platform='win32', stderr=sys.stderr)),
            patch.object(tesseract, '_link_system_binary', return_value=None),
            patch.object(tesseract, '_seven_zip', return_value='7z'),
            patch.object(tesseract, '_download_cached', return_value=setup),
            patch.object(tesseract, '_install_tessdata', side_effect=download),
            patch.object(tesseract.subprocess, 'run', side_effect=extract),
        ):
            self.assertEqual(tesseract.install(self.root, force=True), 0)
        self.assertEqual(custom.read_bytes(), previous_custom)
        for name, data in languages.items():
            self.assertEqual((custom.parent / name).read_bytes(), data)
        self.assertTrue((custom.parent / 'configs/pdf').is_file())
        self.assertTrue((custom.parent.parent / 'libtesseract.dll').is_file())

    def test_tesseract_repair_from_portable_path_does_not_create_a_self_link(self):
        binary = self.file('tesseract/tesseract.exe')
        previous = binary.read_bytes()
        for language in ('rus', 'eng', 'custom'):
            self.file(f'tesseract/tessdata/{language}.traineddata')
        custom = binary.parent / 'tessdata/custom.traineddata'
        custom_before = custom.read_bytes()
        companion = self.file('tesseract/companion.dll')
        companion_before = companion.read_bytes()
        with patch.object(tesseract, 'sys', SimpleNamespace(platform='win32', stderr=sys.stderr)), patch.object(tesseract.shutil, 'which', return_value=str(binary)), patch.object(tesseract, 'download_url') as download:
            self.assertEqual(tesseract.install(self.root, force=True), 0)
        self.assertFalse(binary.is_symlink())
        self.assertEqual(binary.read_bytes(), previous)
        self.assertEqual(custom.read_bytes(), custom_before)
        self.assertEqual(companion.read_bytes(), companion_before)
        download.assert_not_called()

    def test_tesseract_binary_copy_failure_preserves_the_installed_version(self):
        binary = self.file('tesseract/tesseract.exe')
        previous = binary.read_bytes()
        for language in ('rus', 'eng'):
            self.file(f'tesseract/tessdata/{language}.traineddata')
        def failed_binary(root, dest, **kwargs):
            (dest / 'tesseract.exe').write_bytes(b'partial binary')
            raise OSError('copy interrupted')
        with patch.object(tesseract, 'sys', SimpleNamespace(platform='win32', stderr=sys.stderr)), patch.object(tesseract, '_install_tessdata'), patch.object(tesseract, 'install_binary', side_effect=failed_binary):
            self.assertEqual(tesseract.install(self.root, force=True), 1)
        self.assertEqual(binary.read_bytes(), previous)

    def test_tesseract_missing_binary_source_is_not_reported_as_success(self):
        binary = self.file('tesseract/tesseract.exe')
        previous = binary.read_bytes()
        for language in ('rus', 'eng'):
            self.file(f'tesseract/tessdata/{language}.traineddata')
        with patch.object(tesseract, 'sys', SimpleNamespace(platform='win32', stderr=sys.stderr)), patch.object(tesseract, '_install_tessdata'), patch.object(tesseract, 'install_binary', return_value=None):
            self.assertEqual(tesseract.install(self.root, force=True), 1)
        self.assertEqual(binary.read_bytes(), previous)

    def test_tesseract_refresh_reaches_language_and_binary_downloads(self):
        with patch.object(tesseract, 'download_tool_asset') as download:
            tesseract._install_tessdata(self.root / 'staged', root=self.root, refresh=True)
            tesseract._download_cached(self.root, 'https://example.test/binary', 'binary', refresh=True)
        self.assertEqual(download.call_count, 3)
        self.assertTrue(all(call.kwargs['refresh'] for call in download.call_args_list))


if __name__ == '__main__':
    unittest.main()
