"""Чтение celery_workers.yaml без перезаписи."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class WorkerSpec:
    name: str
    hostname: str
    queues: Any
    concurrency: int | None
    pool: str
    loglevel: str
    description: str


@dataclass(frozen=True)
class WorkersFile:
    path: Path
    workers: tuple[WorkerSpec, ...]
    defaults: dict[str, Any]
    exists: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            'path': str(self.path),
            'exists': self.exists,
            'entries': [
                {
                    'name': item.name,
                    'hostname': item.hostname,
                    'queues': item.queues,
                    'concurrency': item.concurrency,
                    'pool': item.pool,
                    'loglevel': item.loglevel,
                    'description': item.description,
                }
                for item in self.workers
            ],
        }


def _as_int(value: Any) -> int | None:
    if value is None or value == '':
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


def load_workers_file(project_root: Path) -> WorkersFile:
    path = project_root / 'celery_workers.yaml'
    exists = path.is_file()
    data: dict[str, Any] = {}
    if exists:
        try:
            loaded = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
            if isinstance(loaded, dict):
                data = loaded
        except Exception:  # noqa: BLE001
            data = {}

    defaults = data.get('defaults') if isinstance(data.get('defaults'), dict) else {}
    default_pool = str(defaults.get('pool') or 'threads')
    default_log = str(defaults.get('loglevel') or 'info')
    raw_workers = data.get('workers') if isinstance(data.get('workers'), dict) else {}

    workers: list[WorkerSpec] = []
    for name, raw in raw_workers.items():
        if not isinstance(raw, dict):
            raw = {}
        workers.append(
            WorkerSpec(
                name=str(name),
                hostname=str(raw.get('hostname') or f'worker@{name}'),
                queues=raw.get('queues', 'all'),
                concurrency=_as_int(raw.get('concurrency')),
                pool=str(raw.get('pool') or default_pool),
                loglevel=str(raw.get('loglevel') or default_log),
                description=str(raw.get('description') or ''),
            )
        )

    if not workers:
        workers.append(
            WorkerSpec(
                name='all',
                hostname='all_worker',
                queues='all',
                concurrency=None,
                pool=default_pool,
                loglevel=default_log,
                description='',
            )
        )

    return WorkersFile(path=path, workers=tuple(workers), defaults=defaults, exists=exists)


def _names_from_workers_file(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except Exception:  # noqa: BLE001
        return set()
    if not isinstance(data, dict):
        return set()
    names: set[str] = set()
    workers = data.get('workers')
    raw_items: list[Any] = []
    if isinstance(workers, list):
        raw_items.extend(workers)
    elif isinstance(workers, dict):
        raw_items.extend(workers.values())
    legacy = data.get('queues')
    if isinstance(legacy, list):
        raw_items.extend(legacy)
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        queues = item.get('queues')
        if isinstance(queues, list):
            names.update(str(name).strip() for name in queues if str(name).strip())
        elif isinstance(queues, str) and queues.strip() and queues.strip() != 'all':
            names.update(part.strip() for part in queues.split(',') if part.strip())
        elif item.get('name') and 'queues' not in item:
            names.add(str(item['name']).strip())
    return {name for name in names if name}


def declared_module_queues(project_root: Path) -> set[str]:
    """Очереди именованных воркеров модулей. Их нет в кэше общего worker."""
    from lifecycle.modules.catalog import ModuleCatalog

    names: set[str] = set()
    try:
        module_dirs = list(ModuleCatalog.from_env(project_root).iter_module_dirs())
    except Exception:  # noqa: BLE001
        return names
    for module_dir in module_dirs:
        names.update(_names_from_workers_file(module_dir / 'celery_workers.yaml'))
        names.update(_names_from_workers_file(module_dir / 'dedicated_queues.yaml'))
    return names


def resolve_worker_queues(queues_config: Any, all_queues: list[str]) -> list[str]:
    if queues_config == 'all' or queues_config is None:
        names = set(all_queues)
        names.add('default')
        return sorted(names)
    if isinstance(queues_config, list):
        return [str(item).strip() for item in queues_config if str(item).strip()]
    if isinstance(queues_config, str):
        return [part.strip() for part in queues_config.split(',') if part.strip()]
    return ['default']
