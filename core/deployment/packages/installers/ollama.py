"""
Установка Ollama в virtual_env/packages/ollama без Django.

Вызов: ergoms package-install ollama [--force] [--refresh]

Регистрация в реестре: core/deployment/packages/core_packages.yaml
"""

from __future__ import annotations

import argparse
import os
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
from packages.archive import download_tool_asset, extract_archive, publish_package  # noqa: E402
from project_layout import (  # noqa: E402
    cache_downloads_dir,
    cache_tmp_dir,
    ensure_dir,
    packages_dir,
)

MIN_ARCHIVE_BYTES = 1024 * 1024


def ollama_dir(root: Path) -> Path:
    return packages_dir(root) / 'ollama'


def ollama_models_dir(root: Path) -> Path:
    return packages_dir(root) / 'ollama_models'


def ollama_exe_name() -> str:
    return 'ollama.exe' if platform.system().lower() == 'windows' else 'ollama'


def is_installed(root: Path) -> bool:
    base = ollama_dir(root)
    name = ollama_exe_name()
    return any(path.is_file() and path.stat().st_size > 0 for path in (base / name, base / 'bin' / name))


def _resolve_archive(machine: str) -> tuple[str, str]:
    system = platform.system().lower()
    machine = machine.lower()

    if system == 'windows':
        if 'arm64' in machine or 'aarch64' in machine:
            name = 'ollama-windows-arm64.zip'
        elif '64' in machine or 'x86_64' in machine or 'amd64' in machine:
            name = 'ollama-windows-amd64.zip'
        else:
            raise RuntimeError(f'Неподдерживаемая архитектура Windows: {machine}')
        return name, 'zip'

    if system == 'linux':
        # С релизов ~0.32 артефакты Linux — tar.zst (старый .tgz удалён → 404).
        if 'x86_64' in machine or 'amd64' in machine:
            name = 'ollama-linux-amd64.tar.zst'
        elif 'arm64' in machine or 'aarch64' in machine:
            name = 'ollama-linux-arm64.tar.zst'
        else:
            raise RuntimeError(f'Неподдерживаемая архитектура Linux: {machine}')
        return name, 'tar.zst'

    raise RuntimeError(f'Неподдерживаемая ОС: {system}')


def _archive_url(archive_name: str) -> str:
    return (
        'https://github.com/ollama/ollama/releases/latest/download/'
        f'{archive_name}'
    )

def _locate_ollama_binary(target_dir: Path) -> Path | None:
    name = ollama_exe_name()
    direct = target_dir / name
    if direct.is_file():
        return direct
    for candidate in (
        target_dir / 'bin' / name,
        target_dir / 'lib' / 'ollama' / name,
    ):
        if candidate.is_file():
            return candidate
    matches = sorted(target_dir.rglob(name))
    return matches[0] if matches else None


def _extract_archive(archive_path: Path, target_dir: Path, archive_type: str) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    if archive_type == 'tar.zst':
        zstd = shutil.which('zstd')
        if not zstd:
            raise RuntimeError('Для распаковки Ollama нужен zstd в PATH.')
        decoded = target_dir.parent / 'ollama.tar'
        with decoded.open('wb') as output:
            result = subprocess.run([zstd, '-d', '-c', str(archive_path)], stdout=output, stderr=subprocess.PIPE, check=False)
        if result.returncode:
            raise RuntimeError('Не удалось распаковать zstd-архив Ollama.')
        extract_archive(decoded, target_dir, 'tar')
    else:
        extract_archive(archive_path, target_dir, archive_type)
    exe = _locate_ollama_binary(target_dir)
    if exe is None or exe.stat().st_size == 0:
        raise RuntimeError('В архиве не найден бинарник Ollama.')
    if not os.access(exe, os.X_OK):
        exe.chmod(exe.stat().st_mode | 0o111)
    target = target_dir / ollama_exe_name()
    if exe.resolve() != target.resolve():
        try:
            target.symlink_to(exe.relative_to(target_dir))
        except OSError:
            shutil.copy2(exe, target)


def _migrate_legacy_models_dir(root: Path) -> None:
    packages = packages_dir(root)
    legacy_models = packages / 'models'
    models_path = ollama_models_dir(root)
    if not legacy_models.is_dir():
        return

    ensure_dir(models_path)
    if any(models_path.iterdir()):
        print(format_console(
            'warning',
            f'Устаревший каталог {legacy_models} не перенесён — '
            f'в {models_path} уже есть данные',
        ))
        return

    for item in legacy_models.iterdir():
        shutil.move(str(item), str(models_path / item.name))

    shutil.rmtree(legacy_models, ignore_errors=True)
    print(format_console(
        'warning',
        f'Данные из packages/models перенесены в {models_path}',
    ))


def install_ollama(root: Path, *, force: bool = False, refresh: bool = False) -> int:
    configure_stdio_utf8()
    target = ollama_dir(root)
    models = ollama_models_dir(root)

    if is_installed(root) and not force:
        print(format_console(
            'warning',
            f'Ollama уже установлен в {target}\n'
            'Используйте --force для переустановки',
        ))
        return 0

    ensure_dir(packages_dir(root))
    ensure_dir(models)
    _migrate_legacy_models_dir(root)

    print('Установка Ollama в packages...')
    archive_name, archive_type = _resolve_archive(platform.machine())
    url = _archive_url(archive_name)
    cache_path = ensure_dir(cache_downloads_dir(root)) / archive_name
    tmp_base = ensure_dir(cache_tmp_dir(root))

    try:
        download_tool_asset(root, 'ollama', url, cache_path, refresh=refresh, archive_type=archive_type, min_bytes=MIN_ARCHIVE_BYTES)
        with tempfile.TemporaryDirectory(dir=str(tmp_base), prefix='pkg_ollama_') as work:
            staged = Path(work) / 'payload'
            _extract_archive(cache_path, staged, archive_type)
            publish_package(root, staged, target)
    except Exception as exc:
        print(format_console('error', f'Ошибка при установке Ollama: {exc}'), file=sys.stderr)
        return 1

    print(format_console('ok', f'Ollama распакован в {target}'))
    print(
        f'\nOllama установлен.\n\n'
        f'Бинарник: {target.absolute()}\n'
        f'Модели: {models.absolute()}\n\n'
        f'OLLAMA_MODELS задаётся автоматически при запуске через ergoms.\n'
        f'Сервер запускается через команды модуля-провайдера.\n'
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Установка Ollama в virtual_env/packages')
    parser.add_argument(
        '--root',
        type=Path,
        default=PROJECT_ROOT,
        help='Корень проекта ERGO MS',
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Переустановить Ollama, даже если он уже установлен',
    )
    parser.add_argument(
        '--refresh',
        action='store_true',
        help='Скачать архив заново, игнорируя кэш в virtual_env/cache/downloads',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    args = build_parser().parse_args(argv)
    return install_ollama(args.root.resolve(), force=args.force, refresh=args.refresh)


if __name__ == '__main__':
    raise SystemExit(main())
