"""
Поставить Chrome for Testing и chromedriver одной Stable-версии.

Без Django. Вызов:
  ergoms package-install chrome-for-testing [--force] [--refresh]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEPLOYMENT_DIR = PROJECT_ROOT / 'core' / 'deployment'
if str(DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOYMENT_DIR))

from console_tags import configure_stdio_utf8, format_console  # noqa: E402
from packages.archive import (  # noqa: E402
    ArchiveInstallError,
    download_tool_asset,
    publish_package,
    extract_archive,
)
from project_layout import (  # noqa: E402
    cache_downloads_dir,
    cache_tmp_dir,
    ensure_dir,
    package_dir,
)

DEST_NAME = 'chrome-for-testing'
VERSIONS_URL = (
    'https://googlechromelabs.github.io/chrome-for-testing/'
    'last-known-good-versions-with-downloads.json'
)
JSON_TIMEOUT_SEC = 60


def chrome_dest(root: Path) -> Path:
    return package_dir(root, DEST_NAME)


def chrome_binary(root: Path) -> Path | None:
    dest = chrome_dest(root)
    if sys.platform == 'win32':
        candidates = (
            dest / 'chrome' / 'chrome.exe',
            dest / 'chrome-win64' / 'chrome.exe',
        )
    else:
        candidates = (
            dest / 'chrome' / 'chrome',
            dest / 'chrome-linux64' / 'chrome',
        )
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def chromedriver_binary(root: Path) -> Path | None:
    dest = chrome_dest(root)
    if sys.platform == 'win32':
        candidates = (
            dest / 'chromedriver' / 'chromedriver.exe',
            dest / 'chromedriver-win64' / 'chromedriver.exe',
        )
    else:
        candidates = (
            dest / 'chromedriver' / 'chromedriver',
            dest / 'chromedriver-linux64' / 'chromedriver',
        )
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def is_installed(root: Path) -> bool:
    dest = chrome_dest(root)
    return (
        (dest / 'VERSION').is_file()
        and chrome_binary(root) is not None
        and chromedriver_binary(root) is not None
    )


def _platform_key() -> str:
    if sys.platform == 'win32':
        return 'win64'
    return 'linux64'


def _fetch_stable() -> tuple[str, str, str]:
    request = urllib.request.Request(
        VERSIONS_URL,
        headers={'User-Agent': 'ergoms/1.0 (chrome-for-testing installer)'},
    )
    with urllib.request.urlopen(request, timeout=JSON_TIMEOUT_SEC) as response:
        payload = json.loads(response.read().decode('utf-8'))
    stable = (payload.get('channels') or {}).get('Stable') or {}
    version = str(stable.get('version') or '').strip()
    downloads = stable.get('downloads') or {}
    plat = _platform_key()

    def _url(kind: str) -> str:
        for item in downloads.get(kind) or []:
            if item.get('platform') == plat:
                return str(item.get('url') or '')
        return ''

    chrome_url = _url('chrome')
    driver_url = _url('chromedriver')
    if not version or not chrome_url or not driver_url:
        raise ArchiveInstallError(
            'В ответе Chrome for Testing нет Stable chrome/chromedriver для этой ОС'
        )
    return version, chrome_url, driver_url


def _chmod_binaries(dest: Path) -> None:
    if sys.platform == 'win32':
        return
    names = {'chrome', 'chromedriver', 'chrome_crashpad_handler', 'chrome_sandbox'}
    for path in dest.rglob('*'):
        if path.is_file() and path.name in names:
            path.chmod(path.stat().st_mode | 0o755)


def _move_extracted_dir(extract_root: Path, dest_subdir: Path) -> None:
    entries = [p for p in extract_root.iterdir() if p.name != '__MACOSX']
    dirs = [p for p in entries if p.is_dir()]
    if dest_subdir.exists():
        shutil.rmtree(dest_subdir)
    if len(dirs) == 1 and len(entries) == 1:
        shutil.move(str(dirs[0]), str(dest_subdir))
        return
    ensure_dir(dest_subdir)
    for item in entries:
        shutil.move(str(item), str(dest_subdir / item.name))


def install(root: Path, *, force: bool = False, refresh: bool = False) -> int:
    dest = chrome_dest(root)
    if is_installed(root) and not force:
        print(format_console('skip', f'chrome-for-testing уже установлен: {dest}'))
        return 0
    try:
        version, chrome_url, driver_url = _fetch_stable()
        downloads = ensure_dir(cache_downloads_dir(root) / DEST_NAME)
        tmp_base = ensure_dir(cache_tmp_dir(root))
        with tempfile.TemporaryDirectory(dir=str(tmp_base), prefix='pkg_chrome_') as work:
            work = Path(work)
            staged = work / 'payload'
            for label, url in (('chrome', chrome_url), ('chromedriver', driver_url)):
                archive = downloads / f'{label}-{version}.zip'
                download_tool_asset(root, DEST_NAME, url, archive, refresh=force or refresh, archive_type='zip')
                extract_root = work / label
                extract_archive(archive, extract_root, 'zip')
                _move_extracted_dir(extract_root, staged / label)
            binary_names = ('chrome.exe', 'chromedriver.exe') if sys.platform == 'win32' else ('chrome', 'chromedriver')
            for folder, binary in zip(('chrome', 'chromedriver'), binary_names):
                path = staged / folder / binary
                if not path.is_file() or path.stat().st_size == 0:
                    raise ArchiveInstallError(f'В архиве отсутствует {binary}')
            _chmod_binaries(staged)
            (staged / 'VERSION').write_text(version + '\n', encoding='utf-8')
            publish_package(root, staged, dest)
    except (ArchiveInstallError, OSError, ValueError) as exc:
        print(format_console('error', str(exc)), file=sys.stderr)
        return 1
    print(format_console('ok', f'Установлено в {dest} (версия {version})'))
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description='Установка Chrome for Testing')
    parser.add_argument('--root', type=Path, default=PROJECT_ROOT)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not (root / 'pyproject.toml').is_file():
        print(format_console('error', f'Корень проекта не найден: {root}'), file=sys.stderr)
        return 1
    return install(root, force=args.force, refresh=args.refresh)


if __name__ == '__main__':
    raise SystemExit(main())
