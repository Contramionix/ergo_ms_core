"""Portable LibreOffice для конвертации DOCX→PDF (рассылки, пропуск, ТКП).

Качает официальный архив The Document Foundation и распаковывает его в
virtual_env/packages/libreoffice, без установки системных пакетов и записи вне корня проекта.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_DEPLOYMENT_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _DEPLOYMENT_DIR.parent.parent
if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))

from console_tags import configure_stdio_utf8, format_console  # noqa: E402
from packages.archive import ArchiveInstallError, download_tool_asset, extract_archive, publish_package  # noqa: E402
from project_layout import (  # noqa: E402
    cache_downloads_dir,
    cache_tmp_dir,
    ensure_dir,
    package_dir,
)

LO_VERSION = '25.8.7'
MIN_ARCHIVE_BYTES = 1024 * 1024

LINUX_ARCHIVE = (
    f'https://download.documentfoundation.org/libreoffice/stable/'
    f'{LO_VERSION}/deb/x86_64/LibreOffice_{LO_VERSION}_Linux_x86-64_deb.tar.gz'
)
WINDOWS_ARCHIVE = (
    f'https://download.documentfoundation.org/libreoffice/stable/'
    f'{LO_VERSION}/win/x86_64/LibreOffice_{LO_VERSION}_Win_x86-64.msi'
)

_SKIP_DEB_MARKERS = (
    'desktop-integration',
    'debian-menus',
    'freedesktop-menus',
    'gnome-integration',
    'kde-integration',
)

_SO_TO_PACKAGE = {
    'libXinerama.so.1': 'libxinerama1',
    'libssl3.so': 'libnss3',
    'libsmime3.so': 'libnss3',
    'libnss3.so': 'libnss3',
    'libnssutil3.so': 'libnss3',
    'libplds4.so': 'libnspr4',
    'libplc4.so': 'libnspr4',
    'libnspr4.so': 'libnspr4',
    'libcairo.so.2': 'libcairo2',
    'libcups.so.2': 'libcups2',
    'libdbus-1.so.3': 'libdbus-1-3',
    'libgio-2.0.so.0': 'libglib2.0-0',
    'libgobject-2.0.so.0': 'libglib2.0-0',
    'libglib-2.0.so.0': 'libglib2.0-0',
    'libX11.so.6': 'libx11-6',
    'libpcre2-8.so.0': 'libpcre2-8-0',
    'libX11-xcb.so.1': 'libx11-xcb1',
    'libdbus-glib-1.so.2': 'libdbus-glib-1-2',
    'libxslt.so.1': 'libxslt1.1',
    'libepoxy.so.0': 'libepoxy0',
    'libharfbuzz.so.0': 'libharfbuzz0b',
    'libfontconfig.so.1': 'libfontconfig1',
    'libfreetype.so.6': 'libfreetype6',
    'libpixman-1.so.0': 'libpixman-1-0',
    'libpng16.so.16': 'libpng16-16',
    'libxcb-render.so.0': 'libxcb-render0',
    'libxcb-shm.so.0': 'libxcb-shm0',
    'librsvg-2.so.2': 'librsvg2-2',
    'libpango-1.0.so.0': 'libpango-1.0-0',
    'libpangocairo-1.0.so.0': 'libpangocairo-1.0-0',
    'libpangoft2-1.0.so.0': 'libpangoft2-1.0-0',
    'libgdk_pixbuf-2.0.so.0': 'libgdk-pixbuf-2.0-0',
    'libavahi-client.so.3': 'libavahi-client3',
    'libavahi-common.so.3': 'libavahi-common3',
    'libgnutls.so.30': 'libgnutls30',
    'libgssapi_krb5.so.2': 'libgssapi-krb5-2',
    'libgraphite2.so.3': 'libgraphite2-3',
    'libthai.so.0': 'libthai0',
    'libdatrie.so.1': 'libdatrie1',
    'libfribidi.so.0': 'libfribidi0',
    'libxcb-xinerama.so.0': 'libxcb-xinerama0',
}


class LibreOfficeInstallError(RuntimeError):
    pass


def linux_marker(dest: Path) -> Path:
    return dest / 'program' / 'soffice'


def windows_marker(dest: Path) -> Path:
    return dest / 'program' / 'soffice.exe'


def skip_deb(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _SKIP_DEB_MARKERS)


def find_program_root(staging: Path, *, executable: str) -> Path | None:
    matches = sorted(staging.rglob(executable))
    for path in matches:
        if path.is_file() and path.parent.name == 'program':
            return path.parent.parent
    return None
def download_archive(url: str, destination: Path, *, refresh: bool, root: Path | None = None) -> None:
    kind = 'tar.gz' if url.endswith('.tar.gz') else 'msi'
    try:
        download_tool_asset(root or _PROJECT_ROOT, 'libreoffice', url, destination, refresh=refresh, archive_type=kind, min_bytes=MIN_ARCHIVE_BYTES)
    except ArchiveInstallError as exc:
        raise LibreOfficeInstallError(str(exc)) from exc


def _extract_deb(deb: Path, staging: Path) -> None:
    dpkg = shutil.which('dpkg-deb')
    if not dpkg:
        raise LibreOfficeInstallError(
            'Нужен dpkg-deb, чтобы распаковать архив LibreOffice на Linux.'
        )
    result = subprocess.run(
        [dpkg, '-x', str(deb), str(staging)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or '').strip()
        raise LibreOfficeInstallError(f'Не удалось распаковать {deb.name}: {stderr[:400]}')


def _chmod_soffice(root: Path) -> None:
    if sys.platform == 'win32':
        return
    for name in ('soffice', 'soffice.bin'):
        path = root / 'program' / name
        if path.is_file():
            path.chmod(path.stat().st_mode | 0o755)


def install_linux(dest: Path, *, work: Path, archive_path: Path) -> None:
    extract_root = work / 'tar'
    staging = work / 'debs'
    ensure_dir(extract_root)
    ensure_dir(staging)
    extract_archive(archive_path, extract_root, 'tar.gz')
    debs = sorted(extract_root.rglob('*.deb'))
    if not debs:
        raise LibreOfficeInstallError('В архиве LibreOffice нет пакетов .deb')
    used = 0
    for deb in debs:
        if skip_deb(deb.name):
            continue
        _extract_deb(deb, staging)
        used += 1
    if used == 0:
        raise LibreOfficeInstallError('После фильтрации не осталось пакетов .deb')
    program_root = find_program_root(staging, executable='soffice')
    if program_root is None:
        raise LibreOfficeInstallError('После распаковки не найден program/soffice')
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(program_root), str(dest))
    _chmod_soffice(dest)
    if not linux_marker(dest).is_file():
        raise LibreOfficeInstallError(f'Не найден маркер: {linux_marker(dest)}')


def install_windows(dest: Path, *, work: Path, archive_path: Path) -> None:
    msiexec = shutil.which('msiexec')
    if not msiexec:
        raise LibreOfficeInstallError('На Windows нужен msiexec, чтобы распаковать MSI LibreOffice.')
    staging = work / 'msi'
    ensure_dir(staging)
    result = subprocess.run(
        [
            msiexec,
            '/a',
            str(archive_path),
            '/qn',
            f'TARGETDIR={staging}',
        ],
        check=False,
    )
    if result.returncode != 0:
        raise LibreOfficeInstallError(f'msiexec завершился с кодом {result.returncode}')
    program_root = find_program_root(staging, executable='soffice.exe')
    if program_root is None:
        raise LibreOfficeInstallError('После распаковки MSI не найден program/soffice.exe')
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(program_root), str(dest))
    if not windows_marker(dest).is_file():
        raise LibreOfficeInstallError(f'Не найден маркер: {windows_marker(dest)}')


def sysroot_lib_dirs(dest: Path) -> list[Path]:
    sysroot = dest / 'sysroot'
    return [
        path for path in (
            sysroot / 'usr' / 'lib' / 'x86_64-linux-gnu',
            sysroot / 'lib' / 'x86_64-linux-gnu',
            dest / 'program',
        )
        if path.is_dir()
    ]


def _ld_library_path(dest: Path) -> str:
    return ':'.join(str(path) for path in sysroot_lib_dirs(dest))


def _missing_shared_libs(dest: Path) -> list[str]:
    binaries = [
        dest / 'program' / 'soffice.bin',
        dest / 'program' / 'oosplash',
        dest / 'program' / 'soffice',
    ]
    env = os.environ.copy()
    lib_path = _ld_library_path(dest)
    if lib_path:
        env['LD_LIBRARY_PATH'] = lib_path
    missing: list[str] = []
    for binary in binaries:
        if not binary.is_file():
            continue
        result = subprocess.run(
            ['ldd', str(binary)],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        for line in (result.stdout or '').splitlines():
            if 'not found' not in line:
                continue
            name = line.strip().split(' ', 1)[0].strip()
            if name and name not in missing:
                missing.append(name)
    return missing


def _guess_package(soname: str) -> str | None:
    mapped = _SO_TO_PACKAGE.get(soname)
    if mapped:
        return mapped
    if not soname.startswith('lib') or '.so' not in soname:
        return None
    stem = soname.split('.so', 1)[0].lower()
    suffix = soname.split('.so', 1)[1]
    if suffix.startswith('.') and suffix[1:].split('.', 1)[0].isdigit():
        return f'{stem}{suffix[1:].split(".", 1)[0]}'
    return stem


def _package_candidates(package: str) -> list[str]:
    names = [package]
    if not package.endswith('t64'):
        names.append(f'{package}t64')
    return names


def _apt_download(package: str, dest_dir: Path) -> bool:
    ensure_dir(dest_dir)
    for candidate in _package_candidates(package):
        before = {path.name for path in dest_dir.glob('*.deb')}
        result = subprocess.run(
            ['apt-get', 'download', candidate],
            cwd=str(dest_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            continue
        after = [path for path in dest_dir.glob('*.deb') if path.name not in before]
        if after:
            return True
    print(format_console('warning', f'Не скачался пакет {package}'))
    return False


def ensure_runtime_libs(dest: Path, *, work: Path) -> None:
    if sys.platform == 'win32':
        return
    sysroot = dest / 'sysroot'
    ensure_dir(sysroot)
    debs_dir = work / 'runtime-debs'
    ensure_dir(debs_dir)
    fetched: set[str] = set()
    for _round in range(12):
        missing = _missing_shared_libs(dest)
        if not missing:
            return
        progressed = False
        for soname in missing:
            package = _guess_package(soname)
            if not package or package in fetched:
                continue
            print(format_console('info', f'Библиотека {soname} → пакет {package}'))
            if _apt_download(package, debs_dir):
                fetched.add(package)
                progressed = True
        if not progressed:
            raise LibreOfficeInstallError(
                'LibreOffice нуждается в библиотеках, которые не удалось скачать: '
                + ', '.join(missing)
            )
        for deb in debs_dir.glob('*.deb'):
            _extract_deb(deb, sysroot)
    leftover = _missing_shared_libs(dest)
    if leftover:
        raise LibreOfficeInstallError(
            'После установки библиотек LibreOffice всё ещё не хватает: '
            + ', '.join(leftover)
        )


def install(root: Path, *, force: bool, refresh: bool) -> None:
    dest = package_dir(root, 'libreoffice')
    marker = windows_marker(dest) if sys.platform == 'win32' else linux_marker(dest)
    tmp_base = ensure_dir(cache_tmp_dir(root))

    if marker.is_file() and marker.stat().st_size > 0 and not force:
        if sys.platform.startswith('linux'):
            with tempfile.TemporaryDirectory(dir=str(tmp_base), prefix='pkg_libreoffice_libs_') as tmp:
                ensure_runtime_libs(dest, work=Path(tmp))
        print(format_console('skip', f'LibreOffice уже установлен: {dest}'))
        return

    if sys.platform == 'win32':
        url = WINDOWS_ARCHIVE
        archive_name = f'LibreOffice_{LO_VERSION}_Win_x86-64.msi'
    elif sys.platform.startswith('linux'):
        url = LINUX_ARCHIVE
        archive_name = f'LibreOffice_{LO_VERSION}_Linux_x86-64_deb.tar.gz'
    else:
        raise LibreOfficeInstallError(
            f'LibreOffice portable для {sys.platform} не поддерживается.'
        )

    cache_path = ensure_dir(cache_downloads_dir(root)) / f'libreoffice-{archive_name}'
    print(format_console('info', f'Установка LibreOffice {LO_VERSION} → {dest}'))
    with tempfile.TemporaryDirectory(dir=str(tmp_base), prefix='pkg_libreoffice_') as tmp:
        work = Path(tmp)
        download_archive(url, cache_path, refresh=refresh, root=root)
        staged = work / 'payload'
        if sys.platform == 'win32':
            install_windows(staged, work=work, archive_path=cache_path)
        else:
            install_linux(staged, work=work, archive_path=cache_path)
            ensure_runtime_libs(staged, work=work)
        (staged / 'VERSION').write_text(f'{LO_VERSION}\n', encoding='utf-8')
        try:
            publish_package(root, staged, dest)
        except ArchiveInstallError as exc:
            raise LibreOfficeInstallError(str(exc)) from exc
    print(format_console('ok', f'LibreOffice {LO_VERSION} установлен: {dest}'))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Portable LibreOffice')
    parser.add_argument('--root', type=Path, default=_PROJECT_ROOT)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        install(root, force=bool(args.force), refresh=bool(args.refresh))
    except (LibreOfficeInstallError, ArchiveInstallError, OSError) as exc:
        print(format_console('error', str(exc)), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
