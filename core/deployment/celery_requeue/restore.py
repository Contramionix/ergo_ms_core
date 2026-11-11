"""Снять незакрытые задачи Redis и вернуть те, чей воркер уже не жив."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from celery_balance.constants import CLUSTER_ON
from celery_balance.queues import _broker_kind, _redis_connect_kwargs
from celery_balance.settings import load_settings
from celery_requeue.consumers import (
    inspect_active_queues,
    resolve_live_queues,
    scan_local_workers,
    swarm_worker_down,
)
from celery_requeue.decide import HEARTBEAT_KEY, STALE_SEC, HeldTask, tags_to_restore
from env_file_loader import load_project_env


@dataclass
class RequeueResult:
    restored: int = 0
    by_queue: dict[str, int] = field(default_factory=dict)
    skipped: str = ''


def _broker_url(kwargs: dict) -> str:
    host = kwargs.get('host') or '127.0.0.1'
    port = kwargs.get('port') or 6379
    db = kwargs.get('db') or 0
    user = str(kwargs.get('username') or '')
    password = str(kwargs.get('password') or '')
    if password:
        auth = (
            f'{quote(user, safe="")}:{quote(password, safe="")}@'
            if user
            else f':{quote(password, safe="")}@'
        )
    elif user:
        auth = f'{quote(user, safe="")}@'
    else:
        auth = ''
    return f'redis://{auth}{host}:{port}/{db}'


def _routing_key(blob: bytes) -> str | None:
    from kombu.utils.json import loads

    try:
        _payload, _exchange, routing_key = loads(blob)
    except Exception:
        return None
    return str(routing_key or '')


def _heartbeats(client) -> dict[str, float]:
    raw = client.hgetall(HEARTBEAT_KEY) or {}
    beats: dict[str, float] = {}
    stale_fields: list[str] = []
    for field_name, value in raw.items():
        tag = field_name.decode() if isinstance(field_name, bytes) else str(field_name)
        text = value.decode() if isinstance(value, bytes) else str(value)
        try:
            stamp = float(text)
        except ValueError:
            stale_fields.append(tag)
            continue
        beats[tag] = stamp
    if stale_fields:
        client.hdel(HEARTBEAT_KEY, *stale_fields)
    return beats


def _drop_heartbeats(client, tags: list[str]) -> None:
    if tags:
        client.hdel(HEARTBEAT_KEY, *tags)


def requeue_orphaned(project_root: Path) -> RequeueResult:
    environ = load_project_env(project_root)
    if _broker_kind(environ) != 'redis':
        return RequeueResult(skipped='not-redis')

    try:
        import redis
    except ImportError:
        return RequeueResult(skipped='redis-down')

    kwargs = _redis_connect_kwargs(project_root, environ)
    kwargs['socket_timeout'] = 5
    kwargs['socket_connect_timeout'] = 5
    try:
        client = redis.Redis(**kwargs)
        client.ping()
    except Exception:
        return RequeueResult(skipped='redis-down')

    raw = client.hgetall('unacked') or {}
    if not raw:
        _drop_orphan_heartbeats(client, set())
        return RequeueResult()

    held: list[HeldTask] = []
    by_tag: dict[str, str] = {}
    for tag_raw, blob in raw.items():
        tag = tag_raw.decode() if isinstance(tag_raw, bytes) else str(tag_raw)
        routing_key = _routing_key(blob)
        if routing_key is None:
            continue
        held.append(HeldTask(tag, routing_key))
        by_tag[tag] = routing_key

    local = scan_local_workers()
    inspected = inspect_active_queues(_broker_url(kwargs))
    cluster_on = load_settings(project_root).cluster == CLUSTER_ON
    live = resolve_live_queues(
        local,
        inspected,
        cluster_on=cluster_on,
        swarm_down=swarm_worker_down() if cluster_on else True,
    )
    now = time.time()
    chosen = tags_to_restore(held, _heartbeats(client), live, now, STALE_SEC)
    if not chosen:
        _drop_orphan_heartbeats(client, set(by_tag))
        if live is None and held:
            return RequeueResult(skipped='unknown-consumers')
        return RequeueResult()

    from kombu import Connection

    restored = Counter()
    done: list[str] = []
    connection = Connection(_broker_url(kwargs), transport_options={'visibility_timeout': 345600})
    try:
        channel = connection.channel()
        for tag in chosen:
            try:
                # rpush: BRPOP/RPOP забирает справа, задача встаёт следующей, не в хвост.
                channel.qos.restore_by_tag(tag, leftmost=False)
            except Exception:
                continue
            restored[by_tag.get(tag, '')] += 1
            done.append(tag)
    finally:
        connection.release()
    _drop_heartbeats(client, done)
    _drop_orphan_heartbeats(client, set(by_tag))
    return RequeueResult(restored=sum(restored.values()), by_queue=dict(restored))


def _drop_orphan_heartbeats(client, live_tags: set[str]) -> None:
    """Пульс уже подтверждённой задачи брокеру больше не нужен."""
    raw = client.hgetall(HEARTBEAT_KEY) or {}
    gone = []
    for field_name in raw:
        tag = field_name.decode() if isinstance(field_name, bytes) else str(field_name)
        if tag not in live_tags:
            gone.append(tag)
    if gone:
        client.hdel(HEARTBEAT_KEY, *gone)
