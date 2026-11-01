"""Кто сейчас слушает очереди: локальные процессы, inspect и Swarm."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from celery_requeue.cmdline import classify_worker_argv

_SWARM_WORKER = 'ergo_workers_ergo-celery-worker'


@dataclass(frozen=True)
class LocalConsumers:
    queues: frozenset[str]
    uncertain: bool
    saw_worker: bool


def scan_local_workers() -> LocalConsumers:
    """Очереди из -Q живых процессов. uncertain — воркер есть, а -Q прочитать нельзя."""
    try:
        import psutil
    except ImportError:
        return LocalConsumers(frozenset(), True, False)

    queues: set[str] = set()
    uncertain = False
    saw_worker = False
    # cmdline читаем в теле цикла: process_iter(attrs=['cmdline']) роняет обход
    # на WinError 87 ещё до yield.
    for proc in psutil.process_iter():
        try:
            argv = [str(part) for part in (proc.cmdline() or [])]
        except (psutil.Error, OSError):
            continue
        classified = classify_worker_argv(argv)
        if not classified.is_worker:
            continue
        saw_worker = True
        if classified.queues is None:
            uncertain = True
            continue
        queues.update(classified.queues)
    return LocalConsumers(frozenset(queues), uncertain, saw_worker)


def inspect_active_queues(broker_url: str, timeout: float = 3.0) -> set[str] | None:
    """None — ни один воркер не ответил или брокер не принял опрос."""
    try:
        from celery import Celery
    except ImportError:
        return None
    app = Celery('ergo_requeue', broker=broker_url)
    try:
        reply = app.control.inspect(timeout=timeout).active_queues()
    except Exception:
        return None
    finally:
        close = getattr(app, 'close', None)
        if close is not None:
            try:
                close()
            except Exception:
                pass
    if not isinstance(reply, dict):
        return None
    names: set[str] = set()
    for queues in reply.values():
        if not isinstance(queues, list):
            continue
        for item in queues:
            if isinstance(item, dict) and item.get('name'):
                names.add(str(item['name']))
    return names


def _service_rows(command: list[str]) -> list[str] | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()


def swarm_worker_down() -> bool | None:
    """True — службы воркера Swarm нет. None — docker не ответил, узел мог остаться."""
    rows = _service_rows(['docker', 'service', 'ls', '--format', '{{.Name}} {{.Replicas}}'])
    if rows is None:
        rows = _service_rows(
            ['sudo', '-n', 'docker', 'service', 'ls', '--format', '{{.Name}} {{.Replicas}}'],
        )
    if rows is None:
        return None
    for line in rows:
        parts = line.split()
        if len(parts) < 2 or parts[0] != _SWARM_WORKER:
            continue
        running = parts[1].split('/', 1)[0]
        return running == '0'
    return True


def resolve_live_queues(
    local: LocalConsumers,
    inspected: set[str] | None,
    *,
    cluster_on: bool,
    swarm_down: bool | None,
) -> set[str] | None:
    """None — потребителей нельзя назвать полностью, чужие задачи не трогаем."""
    remote_unknown = cluster_on and inspected is None and swarm_down is not True
    if local.uncertain or remote_unknown:
        return None
    queues = set(local.queues)
    if inspected is not None:
        queues.update(inspected)
    return queues
