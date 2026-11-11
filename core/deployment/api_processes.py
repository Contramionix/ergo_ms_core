"""Сколько процессов Daphne поднимать и какие порты отдать nginx.

Несколько процессов имеют смысл, только если кэш и channel layer общие
для всех процессов. Иначе права, присутствие и WebSocket разъедутся.
Удалённый NGINX_API_UPSTREAM при API_PROCESSES=auto остаётся одним адресом:
соседние порты чужого хоста отсюда не видны.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from ergo_modes import effective_redis_enabled

# auto не занимает больше этого числа ядер: дальше выигрыш упирается в GIL и БД.
API_PROCESS_CAP = 8
# Явное число тоже ограничено, чтобы опечатка не подняла сотни процессов.
API_PROCESS_HARD_CAP = 32

_SHARED_CACHE = frozenset({'redis', 'file', 'dummy'})
_SHARED_CHANNEL = frozenset({'redis', 'postgres'})
_LOCAL_HOSTS = frozenset({'127.0.0.1', 'localhost', '::1', '0.0.0.0'})


def _text(values: Mapping[str, str], key: str, default: str = '') -> str:
    raw = values.get(key)
    if raw is None:
        return default
    return str(raw).strip()


def cache_backend(values: Mapping[str, str]) -> str:
    explicit = _text(values, 'API_CACHE_BACKEND').lower()
    if explicit:
        return explicit
    if effective_redis_enabled(values):
        return 'redis'
    return 'locmem'


def channel_backend(values: Mapping[str, str]) -> str:
    explicit = _text(values, 'CHANNEL_LAYER_BACKEND').lower()
    if explicit:
        return explicit
    if effective_redis_enabled(values):
        return 'redis'
    return 'memory'


def shared_process_state(values: Mapping[str, str]) -> bool:
    """Кэш и channel layer переживают границу процесса."""
    return cache_backend(values) in _SHARED_CACHE and channel_backend(values) in _SHARED_CHANNEL


def explicit_process_count(raw: str | None) -> int | None:
    """Число из API_PROCESSES. None — auto или пусто."""
    text = (raw if raw is not None else 'auto').strip().lower()
    if text in ('', 'auto'):
        return None
    try:
        count = int(text)
    except ValueError:
        return None
    if count < 1:
        return 1
    return min(count, API_PROCESS_HARD_CAP)


def process_count(
    values: Mapping[str, str],
    *,
    cpu_count: int | None = None,
) -> int:
    """Сколько Daphne запускать. Без общего состояния — всегда один."""
    if not shared_process_state(values):
        return 1
    explicit = explicit_process_count(_text(values, 'API_PROCESSES', 'auto'))
    if explicit is not None:
        return explicit
    cpus = cpu_count if cpu_count and cpu_count > 0 else (os.cpu_count() or 1)
    return max(1, min(int(cpus), API_PROCESS_CAP))


def _reserved_ports(values: Mapping[str, str]) -> set[int]:
    reserved: set[int] = set()
    for key, default in (('MEDIA_API_BIND_PORT', '8003'), ('API_JUPYTER_BIND_PORT', '8002')):
        raw = _text(values, key, default)
        try:
            port = int(raw)
        except ValueError:
            continue
        if port > 0:
            reserved.add(port)
    return reserved


def listen_ports(
    values: Mapping[str, str],
    *,
    base_port: int,
    cpu_count: int | None = None,
) -> list[int]:
    """Порты Daphne, начиная с base_port. Занятые media и Jupyter пропускаются."""
    count = process_count(values, cpu_count=cpu_count)
    reserved = _reserved_ports(values)
    ports: list[int] = []
    candidate = int(base_port)
    limit = candidate + count + len(reserved) + 8
    while len(ports) < count and candidate < limit:
        if candidate not in reserved:
            ports.append(candidate)
        candidate += 1
    return ports or [int(base_port)]


def _is_local_host(host: str) -> bool:
    return host.strip().strip('[]').lower() in _LOCAL_HOSTS


def upstream_servers(
    host: str,
    values: Mapping[str, str],
    *,
    base_port: int,
    always_expand: bool = False,
    cpu_count: int | None = None,
) -> list[str]:
    """Адреса upstream.

    always_expand — контейнер api: порты слушает тот же сетевой namespace.
    Чужой хост при auto не разворачивается: открыт только порт из NGINX_API_UPSTREAM.
    """
    raw = _text(values, 'API_PROCESSES', 'auto')
    remote_single = (
        not always_expand
        and not _is_local_host(host)
        and explicit_process_count(raw) is None
    )
    if remote_single:
        return [f'{host}:{int(base_port)}']
    ports = listen_ports(values, base_port=base_port, cpu_count=cpu_count)
    return [f'{host}:{port}' for port in ports]
