"""Скачивание и распаковка archive-пакетов в virtual_env/packages/."""

from __future__ import annotations

import errno
import os
import hashlib
from http.client import HTTPException
import lzma
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import time
import urllib.request
from urllib.parse import urlparse
import zipfile
import zlib
from uuid import uuid4
from pathlib import Path

_PACKAGES_PKG_DIR = Path(__file__).resolve().parent
_DEPLOYMENT_DIR = _PACKAGES_PKG_DIR.parent
if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))

from console_tags import format_console  # noqa: E402
from project_layout import (  # noqa: E402
    cache_downloads_dir,
    cache_tmp_dir,
    ensure_dir,
    package_dir,
)

from .models import PackageSpec, PlatformArchive  # noqa: E402

DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024
PROGRESS_UPDATE_INTERVAL_SEC = 0.5
DOWNLOAD_USER_AGENT = 'ergoms/1.0 (package installer)'
DOWNLOAD_TIMEOUT_SEC = 300
MIN_ARCHIVE_BYTES = 1024


class ArchiveInstallError(Exception):
    """Ошибка archive-установки."""


def _archive_filename(url: str, archive_type: str) -> str:
    name = Path(urlparse(url).path).name
    if name and '.' in name:
        return name
    ext = {
        'zip': '.zip',
        'tar.gz': '.tar.gz',
        'tgz': '.tgz',
        'tar.xz': '.tar.xz',
    }.get(archive_type, '.bin')
    return f'package{ext}'


def _write_progress(downloaded: int, total_size: int, speed_bps: float) -> None:
    downloaded_mb = downloaded / (1024 * 1024)
    speed_mbps = speed_bps / (1024 * 1024)
    if total_size > 0:
        total_mb = total_size / (1024 * 1024)
        percent = downloaded / total_size * 100
        message = (
            f'\rЗагрузка: {downloaded_mb:.1f}/{total_mb:.1f} МБ '
            f'({percent:.0f}%) {speed_mbps:.1f} МБ/с'
        )
    else:
        message = f'\rЗагрузка: {downloaded_mb:.1f} МБ {speed_mbps:.1f} МБ/с'
    sys.stdout.write(message)
    sys.stdout.flush()


def download_url(url: str, destination: Path) -> None:
    """Скачать url в destination с прогрессом."""
    ensure_dir(destination.parent)
    request = urllib.request.Request(url, headers={'User-Agent': DOWNLOAD_USER_AGENT})
    started = time.monotonic()
    last_print = started
    downloaded = 0
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SEC) as response:
        total_size = int(response.headers.get('Content-Length') or 0)
        with open(destination, 'wb') as out:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_print >= PROGRESS_UPDATE_INTERVAL_SEC:
                    elapsed = max(now - started, 1e-6)
                    _write_progress(downloaded, total_size, downloaded / elapsed)
                    last_print = now
    if downloaded:
        sys.stdout.write('\n')
        sys.stdout.flush()
    if total_size > 0 and downloaded != total_size:
        raise ArchiveInstallError(f'Неполная загрузка {destination.name}: {downloaded} из {total_size} байт')
    if destination.stat().st_size < MIN_ARCHIVE_BYTES:
        raise ArchiveInstallError(f'Слишком маленький архив: {destination}')


def _extract_zip(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path, 'r') as zf:
        for item in zf.infolist():
            target = (destination / item.filename.replace('\\', '/')).resolve()
            if not target.is_relative_to(destination.resolve()) or ':' in item.filename or stat.S_ISLNK(item.external_attr >> 16):
                raise ArchiveInstallError(f'Небезопасный путь в ZIP: {item.filename}')
        zf.extractall(destination)


def _extract_tar(archive_path: Path, destination: Path, mode: str) -> None:
    try:
        with tarfile.open(archive_path, mode) as tf:
            tf.extractall(destination, filter='data')
    except tarfile.TarError as exc:
        raise ArchiveInstallError(f'Небезопасный или повреждённый TAR: {archive_path.name}') from exc


def _verify_download(path: Path, *, sha256=None, archive_type=None, min_bytes=MIN_ARCHIVE_BYTES):
    if not path.is_file() or path.stat().st_size < min_bytes:
        raise ArchiveInstallError(f'Пустой или слишком маленький файл: {path.name}')
    if sha256:
        if not isinstance(sha256, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', sha256):
            raise ArchiveInstallError('Недопустимый SHA256 в описании загрузки')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest.lower() != sha256.lower():
            raise ArchiveInstallError(f'SHA256 не совпадает: {path.name}')
    try:
        if archive_type == 'zip':
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:
                    raise ArchiveInstallError(f'Повреждён ZIP: {path.name}')
        elif archive_type in ('tar.gz', 'tgz', 'tar.xz', 'tar'):
            with tarfile.open(path, 'r:*') as archive:
                archive.getmembers()
                # TAR ends before the compressed footer. Drain it to verify CRC/EOF.
                while archive.fileobj.read(DOWNLOAD_CHUNK_SIZE):
                    pass
        elif archive_type in ('msi', 'tar.zst'):
            with path.open('rb') as stream:
                header = stream.read(8)
            expected = bytes.fromhex('d0cf11e0a1b11ae1') if archive_type == 'msi' else bytes.fromhex('28b52ffd')
            if not header.startswith(expected):
                raise ArchiveInstallError(f'Некорректный {archive_type}: {path.name}')
    except (OSError, zipfile.BadZipFile, tarfile.TarError, EOFError, zlib.error, lzma.LZMAError) as exc:
        raise ArchiveInstallError(f'Повреждён архив: {path.name}') from exc


def download_verified(url, destination, *, mirrors=(), sha256=None, archive_type=None, refresh=False, min_bytes=MIN_ARCHIVE_BYTES, downloader=None):
    """Validate cache and every candidate before replacing the canonical file."""
    destination = Path(destination)
    if destination.is_file() and not refresh:
        try:
            _verify_download(destination, sha256=sha256, archive_type=archive_type, min_bytes=min_bytes)
            return destination
        except ArchiveInstallError:
            print(format_console('warning', f'Повреждён кэш {destination.name}; повторная загрузка'))
    ensure_dir(destination.parent)
    errors = []
    for candidate in dict.fromkeys([url, *mirrors]):
        partial = destination.with_name(destination.name + '.part-' + uuid4().hex)
        try:
            (downloader or download_url)(candidate, partial)
            _verify_download(partial, sha256=sha256, archive_type=archive_type, min_bytes=min_bytes)
            os.replace(partial, destination)
            return destination
        except (OSError, ValueError, HTTPException, ArchiveInstallError) as exc:
            errors.append(f'{candidate}: {exc}')
            print(format_console('warning', f'Источник загрузки недоступен или повреждён: {candidate}'))
        finally:
            partial.unlink(missing_ok=True)
    raise ArchiveInstallError('Не удалось получить проверенный файл: ' + '; '.join(errors))


def download_tool_asset(root, name, url, destination, *, refresh=False, archive_type=None, min_bytes=MIN_ARCHIVE_BYTES, downloader=None):
    """Custom tools share the catalog's optional mirrors and SHA256 policy."""
    from .registry import get_package

    spec = get_package(root, name)
    policy = spec.raw.get('download', {}) if spec else {}
    if not isinstance(policy, dict) or policy.keys() - {'mirrors', 'sha256'}:
        raise ArchiveInstallError(f'{name}: недопустимая download-политика')
    filename = Path(urlparse(url).path).name
    templates = policy.get('mirrors', [])
    hashes = policy.get('sha256', {})
    if not isinstance(templates, list) or not isinstance(hashes, dict):
        raise ArchiveInstallError(f'{name}: недопустимые mirrors/SHA256')
    try:
        mirrors = [template.format(filename=filename, name=name, version=spec.version) for template in templates]
    except (AttributeError, KeyError, ValueError, IndexError) as exc:
        raise ArchiveInstallError(f'{name}: некорректный шаблон зеркала') from exc
    return download_verified(url, destination, mirrors=mirrors, sha256=hashes.get(filename), archive_type=archive_type, refresh=refresh, min_bytes=min_bytes, downloader=downloader)


def _move_into(staged: Path, dest: Path) -> None:
    """Кэш и packages бывают разными точками монтирования (тома воркера Swarm).

    Тогда rename даёт EXDEV даже на одном диске: копируем рядом с dest и подменяем там.
    """
    try:
        os.replace(staged, dest)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    local = dest.with_name(dest.name + '.staging-' + uuid4().hex)
    try:
        shutil.copytree(staged, local, symlinks=True)
        os.replace(local, dest)
    except OSError:
        shutil.rmtree(local, ignore_errors=True)
        raise


def publish_package(root: Path, staged: Path, dest: Path):
    """Commit a validated payload; restore the previous installation on error."""
    base = package_dir(root, '').resolve()
    if dest.resolve() == base or not dest.resolve().is_relative_to(base):
        raise ArchiveInstallError('Каталог установки находится вне packages')
    ensure_dir(dest.parent)
    backup = dest.with_name(dest.name + '.backup-' + uuid4().hex)
    moved = False
    try:
        if dest.exists():
            os.replace(dest, backup)
            moved = True
        _move_into(staged, dest)
    except OSError as exc:
        if moved:
            os.replace(backup, dest)
        raise ArchiveInstallError(f'Не удалось применить пакет {dest.name}') from exc
    if moved:
        if not backup.resolve().is_relative_to(base):
            raise ArchiveInstallError('Резервный каталог находится вне packages')
        try:
            shutil.rmtree(backup)
        except OSError as exc:
            print(format_console('warning', f'Пакет установлен; резервный каталог не удалён: {exc}'))


def extract_archive(archive_path: Path, destination: Path, archive_type: str) -> None:
    ensure_dir(destination)
    kind = archive_type.lower().strip()
    if kind == 'zip':
        _extract_zip(archive_path, destination)
    elif kind in ('tar.gz', 'tgz'):
        _extract_tar(archive_path, destination, 'r:gz')
    elif kind == 'tar.xz':
        _extract_tar(archive_path, destination, 'r:xz')
    elif kind == 'tar':
        _extract_tar(archive_path, destination, 'r:')
    else:
        raise ArchiveInstallError(f'Неподдерживаемый тип архива: {archive_type}')


def _single_top_dir(extract_root: Path) -> Path | None:
    entries = [p for p in extract_root.iterdir() if p.name not in ('__MACOSX',)]
    dirs = [p for p in entries if p.is_dir()]
    files = [p for p in entries if p.is_file()]
    if len(dirs) == 1 and not files:
        return dirs[0]
    return None


def _chmod_executables(root: Path) -> None:
    if sys.platform == 'win32':
        return
    for path in root.rglob('*'):
        if path.is_file() and os.access(path, os.X_OK) is False:
            name = path.name.lower()
            if name.endswith(('.so', '.dylib')):
                continue
            # Типичные бинарники без расширения и *.sh
            if '.' not in path.name or name.endswith(('.sh',)):
                try:
                    path.chmod(path.stat().st_mode | 0o755)
                except OSError:
                    pass


def _apply_pick(extract_root: Path, dest: Path, plat: PlatformArchive) -> None:
    assert plat.pick_match
    matches = sorted(extract_root.glob(plat.pick_match))
    if not matches:
        raise ArchiveInstallError(f'Не найден файл по шаблону {plat.pick_match!r}')
    source = matches[0]
    ensure_dir(dest)
    target_name = plat.pick_as or source.name
    target = dest / target_name
    if dest.exists():
        for child in dest.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
    shutil.copy2(source, target)


def _apply_strip_or_move(extract_root: Path, dest: Path, *, strip_top_dir: bool) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    source = extract_root
    if strip_top_dir:
        top = _single_top_dir(extract_root)
        if top is None:
            raise ArchiveInstallError(
                'strip_top_dir=true, но в архиве нет единственного корневого каталога'
            )
        source = top
    shutil.move(str(source), str(dest))


def install_archive_package(
    root: Path,
    spec: PackageSpec,
    plat: PlatformArchive,
    *,
    force: bool = False,
    refresh: bool = False,
) -> Path:
    """Установить archive-пакет. Возвращает путь dest."""
    from .installer import is_installed, current_platform_key, _nonempty_file

    dest = package_dir(root, spec.dest)
    if is_installed(root, spec) and not force:
        print(format_console('skip', f'{spec.name} уже установлен: {dest}'))
        return dest

    archive_name = _archive_filename(plat.url, plat.archive)
    cache_path = ensure_dir(cache_downloads_dir(root)) / f'{spec.name}-{archive_name}'
    tmp_base = ensure_dir(cache_tmp_dir(root))

    print(format_console('info', f'Установка пакета {spec.name} → {dest}'))
    try:
        with tempfile.TemporaryDirectory(dir=str(tmp_base), prefix=f'pkg_{spec.name}_') as tmp:
            tmp_path = Path(tmp)
            archive_path = download_verified(plat.url, cache_path, mirrors=plat.mirrors, sha256=plat.sha256, archive_type=plat.archive, refresh=refresh)

            extract_root = tmp_path / 'extract'
            ensure_dir(extract_root)
            extract_archive(archive_path, extract_root, plat.archive)

            staged = tmp_path / 'payload'
            if plat.pick_match:
                _apply_pick(extract_root, staged, plat)
            else:
                _apply_strip_or_move(
                    extract_root,
                    staged,
                    strip_top_dir=plat.strip_top_dir,
                )

            _chmod_executables(staged)

            # Для linux ffmpeg и подобных — явный chmod на marker
            final_marker = staged / plat.marker
            if final_marker.is_file() and sys.platform != 'win32':
                try:
                    final_marker.chmod(final_marker.stat().st_mode | 0o755)
                except OSError:
                    pass

            if not _nonempty_file(final_marker, minimum=spec.minimum_sizes.get(plat.marker, 1)):
                raise ArchiveInstallError(
                    f'После установки не найден marker: {final_marker}'
                )
            for alternatives in spec.required_files.get(current_platform_key(), ()):
                if not any(_nonempty_file(staged / path, minimum=spec.minimum_sizes.get(path, 1)) for path in alternatives):
                    raise ArchiveInstallError('В архиве отсутствуют обязательные файлы пакета')
            publish_package(root, staged, dest)
    except ArchiveInstallError:
        raise
    except Exception as exc:
        raise ArchiveInstallError(str(exc)) from exc

    print(format_console('ok', f'Пакет {spec.name} установлен: {dest}'))
    return dest
