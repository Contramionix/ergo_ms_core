"""Архив каталога файлов рядом со снимком SQL. Не знает модулей."""

from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path
from typing import Any

from cli_locale import t
from db_backup_common import BackupError
from deployment_env import read_env

MEDIA_ARCHIVE = 'media.tar.gz'


def resolve_media_dir(root: Path) -> Path:
    raw = (read_env('MEDIA_STORAGE_PATH', '') or '').strip()
    if raw:
        return Path(raw)
    return root / 'media'


def archive_media(root: Path, snapshot: Path) -> dict[str, Any]:
    media = resolve_media_dir(root)
    if not media.is_dir():
        return {'present': False, 'filename': '', 'sha256': '', 'file_count': 0, 'bytes': 0}
    resolved_root = root.resolve()
    resolved_media = media.resolve()
    if resolved_media == resolved_root or resolved_media in resolved_root.parents:
        raise BackupError(t('db_backup_media_unsafe'))
    dest = snapshot / MEDIA_ARCHIVE
    count = 0
    with tarfile.open(dest, 'w:gz') as archive:
        for path in sorted(media.rglob('*')):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(media).as_posix()
            archive.add(path, arcname=rel, recursive=False)
            count += 1
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    return {
        'present': True,
        'filename': MEDIA_ARCHIVE,
        'sha256': digest,
        'file_count': count,
        'bytes': dest.stat().st_size,
    }


def restore_media(root: Path, snapshot: Path, media_info: dict[str, Any] | None) -> None:
    if not media_info or not media_info.get('present'):
        return
    filename = str(media_info.get('filename') or '')
    if filename != MEDIA_ARCHIVE:
        raise BackupError(t('db_backup_media_invalid'))
    archive_path = snapshot / filename
    if not archive_path.is_file():
        raise BackupError(t('db_backup_media_missing'))
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if digest != str(media_info.get('sha256') or ''):
        raise BackupError(t('db_backup_media_checksum'))
    media = resolve_media_dir(root)
    media.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive.getmembers():
            name = member.name.replace('\\', '/')
            if member.issym() or member.islnk() or name.startswith('/') or '..' in name.split('/'):
                raise BackupError(t('db_backup_media_unsafe_path'))
        archive.extractall(media, filter='data')
