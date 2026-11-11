"""Зоны media: префикс пути ведёт на другой каталог или другой media_api.

Файл — ``media_zones.yaml`` в корне проекта. Пустой адрес удалённой зоны
её выключает, и файлы остаются в обычном корне. Самый длинный префикс побеждает.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_ENV = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


@dataclass(frozen=True)
class MediaZone:
    prefix: str
    mode: str
    base_url: str
    root: str
    key: str


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def zones_file() -> Path:
    return project_root() / 'media_zones.yaml'


def load_media_zones(path: Path | None = None) -> tuple[MediaZone, ...]:
    """Прочитать зоны. Нет файла — пустой список, хранилище ведёт себя как раньше."""
    source = path or zones_file()
    if not source.is_file():
        return ()
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError('Для media_zones.yaml нужен PyYAML') from exc
    raw = yaml.safe_load(source.read_text(encoding='utf-8')) or {}
    if not isinstance(raw, dict):
        raise ValueError(f'{source.name}: ожидается словарь с ключом zones')
    items = raw.get('zones') or []
    if not isinstance(items, list):
        raise ValueError(f'{source.name}: zones должен быть списком')
    zones: list[MediaZone] = []
    seen: set[str] = set()
    for item in items:
        zone = _parse_zone(item, source.name)
        if zone is None:
            continue
        if zone.prefix in seen:
            raise ValueError(f'{source.name}: префикс {zone.prefix} задан дважды')
        seen.add(zone.prefix)
        zones.append(zone)
    return tuple(zones)


def match_media_zone(path: str, zones: tuple[MediaZone, ...]) -> MediaZone | None:
    """Самый длинный префикс на границе каталога. ``pages`` не цепляет ``pages_extra``."""
    normalized = str(path or '').replace('\\', '/').strip('/')
    if not normalized or normalized.startswith('/') or '..' in normalized.split('/'):
        return None
    best: MediaZone | None = None
    best_len = -1
    for zone in zones:
        prefix = zone.prefix
        if normalized == prefix or normalized.startswith(prefix + '/'):
            if len(prefix) > best_len:
                best = zone
                best_len = len(prefix)
    return best


def _parse_zone(item: object, filename: str) -> MediaZone | None:
    if not isinstance(item, dict):
        raise ValueError(f'{filename}: элемент zones должен быть словарём')
    prefix = _prefix(str(item.get('prefix') or ''))
    if not prefix:
        raise ValueError(f'{filename}: у зоны пустой prefix')
    mode = str(item.get('mode') or '').strip().lower()
    if mode not in {'remote', 'local'}:
        raise ValueError(f'{filename}: mode зоны {prefix} — remote или local')
    if mode == 'remote':
        base_url = _expand(str(item.get('base_url') or '')).rstrip('/')
        if not base_url:
            return None
        if not base_url.startswith(('http://', 'https://')) or '@' in base_url.split('://', 1)[-1].split('/')[0]:
            raise ValueError(f'{filename}: base_url зоны {prefix} должен быть http(s) без пароля в адресе')
        key_env = str(item.get('key_env') or 'MEDIA_API_INTERNAL_KEY').strip()
        key = os.environ.get(key_env, '').strip()
        if not key:
            raise ValueError(
                f'{filename}: для зоны {prefix} пуст {key_env}. '
                'Служебный ключ media_api на обоих серверах должен совпадать.'
            )
        return MediaZone(prefix=prefix, mode='remote', base_url=base_url, root='', key=key)
    root = _expand(str(item.get('root') or '')).strip()
    if not root:
        return None
    resolved = Path(root).expanduser()
    if not resolved.is_absolute():
        raise ValueError(f'{filename}: root зоны {prefix} должен быть абсолютным путём')
    return MediaZone(prefix=prefix, mode='local', base_url='', root=str(resolved), key='')


def _prefix(value: str) -> str:
    parts = [part for part in value.replace('\\', '/').split('/') if part not in ('', '.')]
    if any(part == '..' for part in parts):
        raise ValueError(f'Недопустимый prefix зоны: {value}')
    return '/'.join(parts)


def _expand(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), '')

    return _ENV.sub(replace, value).strip()
