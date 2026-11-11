"""Очереди из командной строки воркера Celery. Не воркер сюда не попадает."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerArgv:
    is_worker: bool
    queues: frozenset[str] | None


def _queue_argument(argv: list[str]) -> str | None:
    for index, arg in enumerate(argv):
        if arg in ('-Q', '--queues') and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith('--queues='):
            return arg.split('=', 1)[1]
        if arg.startswith('-Q') and len(arg) > 2:
            return arg[2:]
    return None


def classify_worker_argv(argv: list[str]) -> WorkerArgv:
    """queues is None у воркера без -Q: какие очереди он держит, из строки не видно."""
    if not argv:
        return WorkerArgv(False, None)
    lowered = [str(part).lower() for part in argv]
    if 'worker' not in lowered:
        return WorkerArgv(False, None)
    joined = ' '.join(lowered)
    if 'celery' not in joined:
        return WorkerArgv(False, None)
    raw = _queue_argument(argv)
    if raw is None:
        return WorkerArgv(True, None)
    queues = frozenset(part.strip() for part in raw.split(',') if part.strip())
    return WorkerArgv(True, queues)
