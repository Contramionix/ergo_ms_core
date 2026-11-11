from __future__ import annotations

import hashlib
from http.client import IncompleteRead
import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import _bootstrap  # noqa: F401

from packages.archive import ArchiveInstallError, _archive_filename, download_tool_asset, download_url, download_verified, extract_archive, install_archive_package, publish_package
from packages.installer import is_installed
from packages.models import PackageKind, PackageSource, PackageSpec, PlatformArchive
from packages.registry import get_package

ROOT = Path(__file__).resolve().parents[3]


class PackageIntegrityTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'virtual_env/cache/tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base, prefix='test_package_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, name, *, path='bin/demo', payload=None):
        archive = self.root / name
        with zipfile.ZipFile(archive, 'w') as writer:
            writer.writestr(path, payload or os.urandom(4096))
        return archive

    def test_primary_failure_uses_mirror_and_validated_cache_needs_no_source(self):
        archive = self.archive('source.zip')
        expected = hashlib.sha256(archive.read_bytes()).hexdigest()
        cache = self.root / 'cache.zip'
        download_verified((self.root / 'missing.zip').as_uri(), cache, mirrors=[archive.as_uri()], sha256=expected, archive_type='zip')
        archive.unlink()
        download_verified('https://unavailable.invalid/archive.zip', cache, sha256=expected, archive_type='zip')
        self.assertEqual(hashlib.sha256(cache.read_bytes()).hexdigest(), expected)

    def test_checksum_mismatch_and_corrupt_cache_use_a_valid_mirror(self):
        wrong = self.archive('wrong.zip')
        correct = self.archive('correct.zip')
        digest = hashlib.sha256(correct.read_bytes()).hexdigest()
        target = self.root / 'cache.zip'
        target.write_bytes(b'corrupt cache' * 100)
        download_verified(wrong.as_uri(), target, mirrors=[correct.as_uri()], sha256=digest, archive_type='zip')
        self.assertEqual(target.read_bytes(), correct.read_bytes())
        self.assertEqual(list(target.parent.glob('*.part-*')), [])

    def test_all_sources_failing_does_not_replace_valid_existing_cache(self):
        old = self.archive('cache.zip')
        before = old.read_bytes()
        bad = self.root / 'bad.zip'
        bad.write_bytes(b'HTML error' * 500)
        with self.assertRaises(ArchiveInstallError):
            download_verified(bad.as_uri(), old, refresh=True, archive_type='zip')
        self.assertEqual(old.read_bytes(), before)

    def test_interrupted_response_uses_the_next_mirror(self):
        archive = self.archive('source.zip')
        target = self.root / 'cache.zip'
        def interrupted_then_mirror(url, partial):
            if url.endswith('primary.zip'):
                partial.write_bytes(b'partial response')
                raise IncompleteRead(b'partial response', 4096)
            partial.write_bytes(archive.read_bytes())
        download_verified('https://example.test/primary.zip', target, mirrors=['https://example.test/mirror.zip'], archive_type='zip', downloader=interrupted_then_mirror)
        self.assertEqual(target.read_bytes(), archive.read_bytes())

    def test_short_response_with_content_length_is_rejected(self):
        response = io.BytesIO(b'partial' * 300)
        response.headers = {'Content-Length': '4096'}
        with patch('packages.archive.urllib.request.urlopen', return_value=response):
            with self.assertRaises(ArchiveInstallError):
                download_url('https://example.test/model.bin', self.root / 'partial.bin')

    def test_archive_cache_filename_excludes_query_and_fragment(self):
        self.assertEqual(_archive_filename('https://example.test/asset.zip?signature=value#download', 'zip'), 'asset.zip')

    def test_truncated_gzip_footer_is_rejected_before_accepting_the_cache(self):
        archive = self.root / 'complete.tar.gz'
        payload = os.urandom(4096)
        with tarfile.open(archive, 'w:gz') as writer:
            entry = tarfile.TarInfo('bin/demo')
            entry.size = len(payload)
            writer.addfile(entry, io.BytesIO(payload))
        broken = self.root / 'cache.tar.gz'
        broken.write_bytes(archive.read_bytes()[:-8])
        download_verified(archive.as_uri(), broken, archive_type='tar.gz')
        self.assertEqual(broken.read_bytes(), archive.read_bytes())

    def test_custom_tools_use_catalog_mirrors_and_hashes(self):
        archive = self.archive('source.zip')
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        spec = PackageSpec('demo', PackageKind.CUSTOM, 'demo', PackageSource.CORE, raw={'download': {'mirrors': [archive.as_uri()], 'sha256': {'missing.zip': digest}}})
        with patch('packages.registry.get_package', return_value=spec):
            result = download_tool_asset(self.root, 'demo', (self.root / 'missing.zip').as_uri(), self.root / 'cache.zip', archive_type='zip')
        self.assertEqual(hashlib.sha256(result.read_bytes()).hexdigest(), digest)

    def test_zip_traversal_and_symlinks_are_rejected(self):
        for name in ('../outside', 'C:/outside', 'safe/../../outside'):
            archive = self.archive('bad.zip', path=name)
            with self.assertRaises(ArchiveInstallError):
                extract_archive(archive, self.root / 'extract', 'zip')
        archive = self.root / 'symlink.zip'
        with zipfile.ZipFile(archive, 'w') as writer:
            entry = zipfile.ZipInfo('link')
            entry.external_attr = 0o120777 << 16
            writer.writestr(entry, '../outside')
        with self.assertRaises(ArchiveInstallError):
            extract_archive(archive, self.root / 'extract', 'zip')
        self.assertFalse((self.root / 'outside').exists())

    def test_tar_traversal_is_rejected(self):
        archive = self.root / 'bad.tar'
        with tarfile.open(archive, 'w') as writer:
            entry = tarfile.TarInfo('../outside')
            entry.size = 1
            writer.addfile(entry, io.BytesIO(b'x'))
        with self.assertRaises(ArchiveInstallError):
            extract_archive(archive, self.root / 'extract', 'tar')
        self.assertFalse((self.root / 'outside').exists())

    def test_invalid_forced_upgrade_preserves_the_installed_package(self):
        dest = self.root / 'virtual_env/packages/demo'
        (dest / 'bin').mkdir(parents=True)
        marker = dest / 'bin/demo'
        marker.write_bytes(b'old binary')
        archive = self.archive('missing-marker.zip', path='other')
        platform = PlatformArchive(archive.as_uri(), 'zip', 'bin/demo')
        spec = PackageSpec('demo', PackageKind.ARCHIVE, 'demo', PackageSource.CORE, platforms={'windows': platform, 'linux': platform})
        with self.assertRaises(ArchiveInstallError):
            install_archive_package(self.root, spec, platform, force=True)
        self.assertEqual(marker.read_bytes(), b'old binary')

    def test_short_marker_in_archive_does_not_replace_previous_package(self):
        dest = self.root / 'virtual_env/packages/demo'
        (dest / 'bin').mkdir(parents=True)
        marker = dest / 'bin/demo'
        marker.write_bytes(b'previous binary')
        archive = self.archive('short.zip')
        platform = PlatformArchive(archive.as_uri(), 'zip', 'bin/demo')
        spec = PackageSpec('demo', PackageKind.ARCHIVE, 'demo', PackageSource.CORE, platforms={'windows': platform, 'linux': platform}, minimum_sizes={'bin/demo': 8192})
        with self.assertRaises(ArchiveInstallError):
            install_archive_package(self.root, spec, platform, force=True)
        self.assertEqual(marker.read_bytes(), b'previous binary')

    def test_publish_failure_restores_the_previous_directory(self):
        dest = self.root / 'virtual_env/packages/demo'
        dest.mkdir(parents=True)
        (dest / 'old').write_bytes(b'old')
        staged = self.root / 'staged'
        staged.mkdir()
        (staged / 'new').write_bytes(b'new')
        replace = os.replace
        calls = 0
        def fail_once(source, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('simulated publish failure')
            return replace(source, target)
        with patch('packages.archive.os.replace', side_effect=fail_once):
            with self.assertRaises(ArchiveInstallError):
                publish_package(self.root, staged, dest)
        self.assertEqual((dest / 'old').read_bytes(), b'old')

    def test_version_marker_alone_does_not_mark_chrome_or_ocr_ready(self):
        for name in ('chrome-for-testing', 'tesseract'):
            spec = get_package(self.root, name)
            dest = self.root / 'virtual_env/packages' / spec.dest
            dest.mkdir(parents=True)
            (dest / 'VERSION').write_text('version', encoding='utf-8')
            with patch('packages.installer.current_platform_key', return_value='windows'):
                self.assertFalse(is_installed(self.root, spec))


if __name__ == '__main__':
    unittest.main()
