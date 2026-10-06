"""Снимок каталога файлов рядом с дампом базы."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _bootstrap  # noqa: F401

from media_backup import archive_media, resolve_media_dir, restore_media


class MediaBackupTests(unittest.TestCase):
    def test_roundtrip_keeps_bytes_and_count(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            media = root / 'media' / 'lms'
            media.mkdir(parents=True)
            (media / 'note.txt').write_text('привет', encoding='utf-8')
            snapshot = root / 'snapshot'
            snapshot.mkdir()
            with patch('media_backup.resolve_media_dir', return_value=root / 'media'):
                info = archive_media(root, snapshot)
                self.assertTrue(info['present'])
                self.assertEqual(info['file_count'], 1)
                (root / 'media' / 'lms' / 'note.txt').write_text('other', encoding='utf-8')
                restore_media(root, snapshot, info)
            self.assertEqual((root / 'media' / 'lms' / 'note.txt').read_text(encoding='utf-8'), 'привет')

    def test_default_dir_is_project_media(self) -> None:
        root = Path('/work/ergo')
        with patch('media_backup.read_env', return_value=''):
            self.assertEqual(resolve_media_dir(root), root / 'media')
