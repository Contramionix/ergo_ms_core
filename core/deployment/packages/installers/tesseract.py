"""
Поставить Tesseract и tessdata rus/eng в virtual_env/packages/tesseract.

Без Django и без apt. Linux — статичный бинарь, Windows — системный PATH
или распаковка официального установщика через 7-Zip. Вызов:
  ergoms package-install tesseract [--force] [--refresh]
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEPLOYMENT_DIR = PROJECT_ROOT / 'core' / 'deployment'
if str(DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOYMENT_DIR))

from console_tags import configure_stdio_utf8, format_console  # noqa: E402
from packages.archive import ArchiveInstallError, download_url, download_tool_asset, publish_package  # noqa: E402
from project_layout import cache_downloads_dir, cache_tmp_dir, ensure_dir, package_dir  # noqa: E402

DEST_NAME = 'tesseract'
VERSION = '5.5.3'
LINUX_RELEASE = (
    'https://github.com/DanielMYT/tesseract-static/releases/download/'
    'tesseract-5.5.3-rebuild'
)
WINDOWS_SETUP = (
    'https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/'
    'tesseract-ocr-w64-setup-5.5.3.20260724.exe'
)
TESSDATA = (
    (
        'rus.traineddata',
        'https://github.com/tesseract-ocr/tessdata/raw/main/rus.traineddata',
    ),
    (
        'eng.traineddata',
        'https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata',
    ),
)


def tesseract_dest(root: Path) -> Path:
    return package_dir(root, DEST_NAME)


def binary_relpath() -> str:
    return 'tesseract.exe' if sys.platform == 'win32' else 'bin/tesseract'


def binary_path(dest: Path) -> Path:
    return dest / binary_relpath()


def tessdata_ready(dest: Path) -> bool:
    data_dir = dest / 'tessdata'
    return all((data_dir / name).is_file() and (data_dir / name).stat().st_size >= 1024 for name, _url in TESSDATA)


def is_complete(dest: Path) -> bool:
    binary = binary_path(dest)
    return binary.is_file() and binary.stat().st_size > 1024 and tessdata_ready(dest)


def linux_binary_url(machine: str | None = None) -> str:
    arch = (machine or platform.machine() or '').lower()
    if arch in {'x86_64', 'amd64'}:
        name = 'tesseract.x86_64'
    elif arch in {'aarch64', 'arm64'}:
        name = 'tesseract.aarch64'
    else:
        raise ArchiveInstallError(f'Нет portable Tesseract для архитектуры {arch}')
    return f'{LINUX_RELEASE}/{name}'


def write_version(dest: Path) -> None:
    (dest / 'VERSION').write_text(VERSION + '\n', encoding='utf-8')


def _download_cached(root: Path, url: str, filename: str, *, refresh: bool = False) -> Path:
    cached = cache_downloads_dir(root) / filename
    return download_tool_asset(root, DEST_NAME, url, cached, refresh=refresh, downloader=download_url)


def _install_tessdata(dest: Path, *, root: Path | None = None, refresh: bool = False) -> Path:
    data_dir = ensure_dir(dest / 'tessdata')
    for name, url in TESSDATA:
        download_tool_asset(root or PROJECT_ROOT, DEST_NAME, url, data_dir / name, refresh=refresh, downloader=download_url)
    return data_dir


def _link_system_binary(dest: Path, *, managed_dest: Path | None = None) -> Path | None:
    which = shutil.which('tesseract')
    if not which:
        return None
    source = Path(which)
    target = binary_path(dest)
    ensure_dir(target.parent)
    if source.resolve() == target.resolve():
        return target
    if target.exists() or target.is_symlink():
        target.unlink()
    if managed_dest and source.resolve().is_relative_to(managed_dest.resolve()):
        # A link to the old portable binary would point to itself after publication.
        shutil.copy2(source, target)
        return target
    try:
        target.symlink_to(source)
    except OSError:
        shutil.copy2(source, target)
    return target


def _install_linux_binary(root: Path, dest: Path, *, refresh: bool = False) -> Path:
    url = linux_binary_url()
    cached = _download_cached(root, url, Path(url).name, refresh=refresh)
    target = binary_path(dest)
    ensure_dir(target.parent)
    shutil.copy2(cached, target)
    target.chmod(target.stat().st_mode | 0o755)
    return target


def _seven_zip() -> str | None:
    for name in ('7z', '7za', '7z.exe'):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        Path(r'C:\Program Files\7-Zip\7z.exe'),
        Path(r'C:\Program Files (x86)\7-Zip\7z.exe'),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _install_windows_binary(root: Path, dest: Path, *, refresh: bool = False) -> Path | None:
    linked = _link_system_binary(dest, managed_dest=tesseract_dest(root))
    if linked is not None:
        return linked
    seven = _seven_zip()
    if not seven:
        return None
    setup = _download_cached(root, WINDOWS_SETUP, Path(WINDOWS_SETUP).name, refresh=refresh)
    tmp_base = ensure_dir(cache_tmp_dir(root))
    with tempfile.TemporaryDirectory(dir=tmp_base, prefix='tesseract-nsis_') as work:
        extract_dir = Path(work)
        result = subprocess.run(
            [seven, 'x', '-y', f'-o{extract_dir}', str(setup)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ArchiveInstallError(result.stderr.strip() or '7-Zip не распаковал установщик Tesseract')
        found = next(extract_dir.rglob('tesseract.exe'), None)
        if found is None:
            raise ArchiveInstallError('В установщике Tesseract нет tesseract.exe')
        for item in found.parent.iterdir():
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
    return dest / 'tesseract.exe'


def install_binary(root: Path, dest: Path, *, refresh: bool = False) -> Path | None:
    if sys.platform == 'win32':
        return _install_windows_binary(root, dest, refresh=refresh)
    return _install_linux_binary(root, dest, refresh=refresh)


def install(root: Path, *, force: bool = False, refresh: bool = False) -> int:
    dest = tesseract_dest(root)
    if is_complete(dest) and not force:
        print(format_console('skip', f'tesseract уже установлен: {binary_path(dest)}'))
        return 0
    try:
        tmp_base = ensure_dir(cache_tmp_dir(root))
        with tempfile.TemporaryDirectory(dir=tmp_base, prefix='pkg_tesseract_') as work:
            staged = Path(work) / 'payload'
            if dest.is_dir():
                # Preserve existing dictionaries and companion libraries during repair.
                shutil.copytree(dest, staged)
            else:
                staged.mkdir()
            binary = install_binary(root, staged, refresh=refresh)
            _install_tessdata(staged, root=root, refresh=refresh)
            if binary is None or not is_complete(staged):
                raise ArchiveInstallError(
                    'Не удалось подготовить полный Tesseract. '
                    'На Windows нужен tesseract в PATH или 7-Zip для распаковки установщика.'
                )
            write_version(staged)
            publish_package(root, staged, dest)
    except (ArchiveInstallError, OSError) as exc:
        print(format_console('error', str(exc)), file=sys.stderr)
        return 1
    print(format_console('ok', f'Tesseract: {binary_path(dest)}'))
    print(format_console('ok', f'tessdata: {dest / "tessdata"}'))
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description='Install portable Tesseract into virtual_env/packages')
    parser.add_argument('--root', default=str(PROJECT_ROOT))
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args(argv)
    return install(Path(args.root), force=bool(args.force), refresh=bool(args.refresh))


if __name__ == '__main__':
    raise SystemExit(main())
