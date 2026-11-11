"""
Discovery portable-пакетов: core_packages.yaml + modules/*/packages.yaml.

Вне Django. Имена модулей не хардкодятся — только ModuleCatalog.
"""

from __future__ import annotations

import sys
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml

_PACKAGES_DIR = Path(__file__).resolve().parent
_DEPLOYMENT_DIR = _PACKAGES_DIR.parent
if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))

from console_tags import format_console  # noqa: E402
from lifecycle.modules.catalog import ModuleCatalog  # noqa: E402
from yaml_documents import DuplicateYamlKeyError, load_unique_yaml  # noqa: E402

from .models import PackageKind, PackageSource, PackageSpec, PlatformArchive  # noqa: E402

CORE_PACKAGES_FILENAME = 'core_packages.yaml'
MODULE_PACKAGES_FILENAME = 'packages.yaml'


class PackageRegistryError(Exception):
    """Ошибка загрузки или слияния реестра пакетов."""


def _safe_relative(value: str, context: str) -> str:
    normalized = value.replace('\\', '/')
    path = PurePosixPath(normalized)
    if not normalized or path == PurePosixPath('.') or path.is_absolute() or PureWindowsPath(normalized).drive or '..' in path.parts:
        raise PackageRegistryError(f'{context}: путь должен находиться внутри каталога пакета')
    return normalized


def _warn(message: str) -> None:
    print(format_console('warning', message), file=sys.stderr)


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if text:
                items.append(text)
        return items
    return []


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    return tuple(_as_str_list(value))


def _parse_platform(data: Any, *, package_name: str, platform: str) -> PlatformArchive | None:
    if not isinstance(data, dict):
        _warn(f'Пакет {package_name}: platforms.{platform} должен быть объектом')
        return None
    url = str(data.get('url') or '').strip()
    if not url:
        _warn(f'Пакет {package_name}: platforms.{platform}.url обязателен')
        return None
    archive = str(data.get('archive') or 'zip').strip().lower()
    marker = str(data.get('marker') or '').strip()
    if not marker:
        _warn(f'Пакет {package_name}: platforms.{platform}.marker обязателен')
        return None
    pick = data.get('pick')
    pick_match: str | None = None
    pick_as: str | None = None
    if isinstance(pick, dict):
        pick_match = str(pick.get('match') or '').strip() or None
        pick_as = str(pick.get('as') or '').strip() or None
        if pick_match:
            pick_match = _safe_relative(pick_match, package_name)
        if pick_as:
            pick_as = _safe_relative(pick_as, package_name)
    strip_top = bool(data.get('strip_top_dir', False))
    sha256 = data.get('sha256')
    if sha256 is not None and (not isinstance(sha256, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', sha256)):
        raise PackageRegistryError(f'Пакет {package_name}: недопустимый SHA256')
    mirrors = data.get('mirrors', [])
    if not isinstance(mirrors, list) or any(not isinstance(url, str) or not url for url in mirrors):
        raise PackageRegistryError(f'Пакет {package_name}: mirrors должен быть списком URL')
    return PlatformArchive(
        url=url,
        archive=archive,
        marker=_safe_relative(marker, package_name),
        pick_match=pick_match,
        pick_as=pick_as,
        strip_top_dir=strip_top,
        mirrors=tuple(mirrors),
        sha256=sha256.lower() if sha256 else None,
    )


def _parse_package(
    name: str,
    data: Any,
    *,
    source: PackageSource,
    module: str | None = None,
    module_dir: Path | None = None,
) -> PackageSpec | None:
    if not isinstance(data, dict):
        _warn(f'Пакет {name}: описание должно быть объектом')
        return None

    kind_raw = str(data.get('kind') or '').strip().lower()
    try:
        kind = PackageKind(kind_raw)
    except ValueError:
        _warn(f'Пакет {name}: неизвестный kind={kind_raw!r} (ожидается archive|custom)')
        return None

    dest = str(data.get('dest') or name).strip()
    if not dest or '/' in dest or '\\' in dest or ':' in dest or dest in ('.', '..'):
        _warn(f'Пакет {name}: некорректный dest={dest!r}')
        return None

    version = str(data.get('version') or '').strip()
    installer = str(data.get('installer') or '').strip() or None
    installer_args = _as_str_tuple(data.get('installer_args'))
    pass_root = bool(data.get('pass_root', True))
    marker_windows = str(data.get('marker_windows') or '').strip() or None
    marker_linux = str(data.get('marker_linux') or '').strip() or None
    extra_dirs = _as_str_tuple(data.get('extra_dirs'))
    marker_windows = _safe_relative(marker_windows, name) if marker_windows else None
    marker_linux = _safe_relative(marker_linux, name) if marker_linux else None
    extra_dirs = tuple(_safe_relative(path, name) for path in extra_dirs)
    always_run = bool(data.get('always_run', False))
    swarm_worker = bool(data.get('swarm_worker', False))
    policy = data.get('download', {})
    if not isinstance(policy, dict) or policy.keys() - {'mirrors', 'sha256'}:
        raise PackageRegistryError(f'Пакет {name}: недопустимая download-политика')
    mirrors = policy.get('mirrors', [])
    hashes = policy.get('sha256', {})
    if not isinstance(mirrors, list) or any(not isinstance(url, str) or not url for url in mirrors):
        raise PackageRegistryError(f'Пакет {name}: download.mirrors должен быть списком URL')
    if not isinstance(hashes, dict) or any(not isinstance(filename, str) or not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', digest) for filename, digest in hashes.items()):
        raise PackageRegistryError(f'Пакет {name}: недопустимые download.sha256')
    for template in mirrors:
        try:
            template.format(filename='asset.zip', name=name, version=version)
        except (AttributeError, KeyError, ValueError, IndexError) as exc:
            raise PackageRegistryError(f'Пакет {name}: некорректный шаблон зеркала') from exc

    platforms: dict[str, PlatformArchive] = {}
    required_files = {}
    minimum_sizes = data.get('minimum_sizes', {})
    if not isinstance(minimum_sizes, dict):
        raise PackageRegistryError(f'Пакет {name}: minimum_sizes должен быть объектом')
    parsed_sizes = {}
    for path, size in minimum_sizes.items():
        if not isinstance(path, str) or type(size) is not int or size < 1:
            raise PackageRegistryError(f'Пакет {name}: minimum_sizes допускает относительный путь и положительное целое число байт')
        parsed_sizes[_safe_relative(path, name)] = size
    required_raw = data.get('required_files', {})
    if not isinstance(required_raw, dict):
        raise PackageRegistryError(f'Пакет {name}: required_files должен быть объектом')
    for key, groups in required_raw.items():
        if not isinstance(groups, list):
            raise PackageRegistryError(f'Пакет {name}: required_files.{key} должен быть списком')
        parsed_groups = []
        for group in groups:
            choices = [group] if isinstance(group, str) else group
            if not isinstance(choices, list) or not choices or any(not isinstance(item, str) for item in choices):
                raise PackageRegistryError(f'Пакет {name}: недопустимые required_files')
            parsed_groups.append(tuple(_safe_relative(item, name) for item in choices))
        required_files[str(key)] = tuple(parsed_groups)
    platforms_raw = data.get('platforms')
    if platforms_raw is not None:
        if not isinstance(platforms_raw, dict):
            _warn(f'Пакет {name}: platforms должен быть объектом')
            return None
        for plat_name, plat_data in platforms_raw.items():
            parsed = _parse_platform(plat_data, package_name=name, platform=str(plat_name))
            if parsed is not None:
                platforms[str(plat_name).strip().lower()] = parsed

    if kind == PackageKind.ARCHIVE and not platforms:
        _warn(f'Пакет {name}: для kind=archive нужна секция platforms')
        return None
    if kind == PackageKind.CUSTOM and not installer:
        _warn(f'Пакет {name}: для kind=custom нужен installer')
        return None

    return PackageSpec(
        name=name,
        kind=kind,
        dest=dest,
        source=source,
        version=version,
        module=module,
        module_dir=module_dir,
        installer=installer,
        installer_args=installer_args,
        pass_root=pass_root,
        marker_windows=marker_windows,
        marker_linux=marker_linux,
        extra_dirs=extra_dirs,
        always_run=always_run,
        swarm_worker=swarm_worker,
        platforms=platforms,
        supported_platforms=_as_str_tuple(data.get('supported_platforms')),
        required_files=required_files,
        minimum_sizes=parsed_sizes,
        raw=dict(data),
    )


def _load_yaml(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError) as exc:
        _warn(f'Не удалось прочитать {path}: {exc}')
        return None
    if not text.strip():
        _warn(f'{path}: файл пуст')
        return None
    try:
        data = load_unique_yaml(text)
    except DuplicateYamlKeyError as exc:
        raise PackageRegistryError(f'{path}: {exc}') from exc
    except yaml.YAMLError as exc:
        _warn(f'{path}: ошибка YAML: {exc}')
        return None
    if not isinstance(data, dict):
        _warn(f'{path}: корень должен быть объектом')
        return None
    return data


def _load_core_packages() -> dict[str, PackageSpec]:
    path = _PACKAGES_DIR / CORE_PACKAGES_FILENAME
    if not path.is_file():
        raise PackageRegistryError(f'Не найден манифест ядра: {path}')
    data = _load_yaml(path)
    if data is None:
        raise PackageRegistryError(f'Не удалось загрузить {path}')
    packages_raw = data.get('packages')
    if not isinstance(packages_raw, dict):
        raise PackageRegistryError(f'{path}: секция packages обязательна')

    result: dict[str, PackageSpec] = {}
    for name, pkg_data in packages_raw.items():
        key = str(name).strip()
        if not key:
            continue
        spec = _parse_package(key, pkg_data, source=PackageSource.CORE)
        if spec is not None:
            result[key] = spec
    return result


def _load_module_packages(
    project_root: Path,
    *,
    existing: dict[str, PackageSpec],
) -> dict[str, PackageSpec]:
    catalog = ModuleCatalog.from_env(project_root)
    added: dict[str, PackageSpec] = {}

    for module_dir in catalog.iter_module_dirs():
        path = module_dir / MODULE_PACKAGES_FILENAME
        if not path.is_file():
            continue
        data = _load_yaml(path)
        if data is None:
            continue
        module_name = str(data.get('module') or module_dir.name).strip() or module_dir.name
        packages_raw = data.get('packages')
        if not isinstance(packages_raw, dict):
            _warn(f'{path}: секция packages обязательна')
            continue
        for name, pkg_data in packages_raw.items():
            key = str(name).strip()
            if not key:
                continue
            if isinstance(pkg_data, dict) and 'use' in pkg_data:
                if set(pkg_data) != {'use'} or pkg_data['use'] != key or key not in existing:
                    raise PackageRegistryError(f'{path}: недопустимая ссылка use для {key}')
                continue
            if key in existing or key in added:
                owner = existing.get(key) or added.get(key)
                owner_label = (
                    f'ядро'
                    if owner and owner.source == PackageSource.CORE
                    else f'модуль {owner.module if owner else "?"}'
                )
                raise PackageRegistryError(
                    f'Конфликт имени пакета {key!r}: уже зарегистрирован ({owner_label}), '
                    f'повтор в {path}'
                )
            spec = _parse_package(
                key,
                pkg_data,
                source=PackageSource.MODULE,
                module=module_name,
                module_dir=module_dir,
            )
            if spec is not None:
                added[key] = spec
    return added


def discover_packages(project_root: Path | str) -> dict[str, PackageSpec]:
    """Полный реестр: ядро + модули. При конфликте имён — PackageRegistryError."""
    root = Path(project_root).resolve()
    packages = _load_core_packages()
    packages.update(_load_module_packages(root, existing=packages))
    return packages


def get_package(project_root: Path | str, name: str) -> PackageSpec | None:
    return discover_packages(project_root).get(name)
