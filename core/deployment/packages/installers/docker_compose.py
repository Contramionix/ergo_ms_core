"""
Portable Docker Compose v2 в virtual_env/packages/docker-compose без Django.

Бинарник не архив: скачивается один файл релиза, проверяется размер и кладётся в каталог пакета.
Вызов: ergoms package-install docker-compose [--force] [--refresh]

Регистрация в реестре: core/deployment/packages/core_packages.yaml
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEPLOYMENT_DIR = PROJECT_ROOT / 'core' / 'deployment'
if str(DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOYMENT_DIR))

from console_tags import configure_stdio_utf8, format_console  # noqa: E402
from packages.archive import download_tool_asset, download_url, publish_package  # noqa: E402
from project_layout import cache_downloads_dir, cache_tmp_dir, ensure_dir, package_dir  # noqa: E402

DEST_NAME = 'docker-compose'
VERSION = 'v2.29.7'
# Компоуз v2 без плагина: тот же набор подкоманд, что и у `docker compose`.
MIN_BINARY_BYTES = 10 * 1024 * 1024


def _asset_name() -> str:
    machine = platform.machine().lower()
    if machine in {'x86_64', 'amd64'}:
        return 'docker-compose-linux-x86_64'
    if machine in {'aarch64', 'arm64'}:
        return 'docker-compose-linux-aarch64'
    raise RuntimeError(f'Неподдерживаемая архитектура Linux для Docker Compose: {machine}')


def is_installed(root: Path) -> bool:
    binary = package_dir(root, DEST_NAME) / 'docker-compose'
    return binary.is_file() and binary.stat().st_size >= MIN_BINARY_BYTES


def install(root: Path, *, force: bool = False, refresh: bool = False) -> int:
    if platform.system().lower() != 'linux':
        print(format_console('error', 'Portable Docker Compose поддерживается только на Linux.'))
        return 1
    dest = package_dir(root, DEST_NAME)
    if is_installed(root) and not force:
        print(format_console('ok', f'Docker Compose уже установлен: {dest}'))
        return 0

    asset = _asset_name()
    url = f'https://github.com/docker/compose/releases/download/{VERSION}/{asset}'
    data_dir = ensure_dir(cache_downloads_dir(root))
    staged_root = ensure_dir(cache_tmp_dir(root))
    staged = Path(tempfile.mkdtemp(prefix='docker-compose-', dir=staged_root))
    try:
        downloaded = download_tool_asset(
            root,
            DEST_NAME,
            url,
            data_dir / asset,
            refresh=refresh,
            min_bytes=MIN_BINARY_BYTES,
            downloader=download_url,
        )
        binary = staged / 'docker-compose'
        shutil.copy2(downloaded, binary)
        binary.chmod(binary.stat().st_mode | 0o755)
        if not os.access(binary, os.X_OK):
            raise RuntimeError('Бинарник Docker Compose не стал исполняемым')
        publish_package(root, staged, dest)
    except Exception as exc:
        print(format_console('error', f'Docker Compose не установлен: {exc}'))
        return 1
    finally:
        shutil.rmtree(staged, ignore_errors=True)
    print(format_console('ok', f'Docker Compose {VERSION} установлен: {dest / "docker-compose"}'))
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description='Install portable Docker Compose v2 into virtual_env/packages')
    parser.add_argument('--root', default=str(PROJECT_ROOT))
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args(argv)
    return install(Path(args.root), force=bool(args.force), refresh=bool(args.refresh))


if __name__ == '__main__':
    raise SystemExit(main())
