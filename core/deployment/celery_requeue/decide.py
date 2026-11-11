"""Кого возвращать в очередь. Без Redis и без процессов — это проверяют тесты."""

from __future__ import annotations

from dataclasses import dataclass

# Тот же ключ пишет пульс воркера. Короткий visibility_timeout здесь не используем:
# живой обход держит задачу часами, и брокер не должен отдавать её второму воркеру.
HEARTBEAT_KEY = 'ergo:celery:unacked_heartbeat'
HEARTBEAT_INTERVAL_SEC = 10
# Девять пропущенных пульсов. Ниже начинает мешать разъезд часов между узлами.
STALE_SEC = 90


@dataclass(frozen=True)
class HeldTask:
    tag: str
    routing_key: str


def tags_to_restore(
    held: list[HeldTask],
    heartbeats: dict[str, float],
    live_queues: set[str] | None,
    now: float,
    stale_sec: float = STALE_SEC,
) -> list[str]:
    """Какие delivery tag вернуть в очередь.

    live_queues is None — список потребителей не удалось снять. Тогда трогаем
    только протухший пульс: свежую задачу живого воркера не дублируем.
    Пустой set — потребителей нет, задачу можно вернуть сразу, даже если пульс
    ещё свежий: его написал процесс, который уже умер.
    Очередь ещё слушают, но пульс этого tag протух — умер один из воркеров,
    второй продолжает слушать ту же очередь.
    """
    restore: list[str] = []
    for item in held:
        beat = heartbeats.get(item.tag)
        fresh = beat is not None and (now - beat) < stale_sec
        stale = beat is not None and not fresh
        if live_queues is None:
            if stale:
                restore.append(item.tag)
            continue
        if item.routing_key not in live_queues:
            restore.append(item.tag)
            continue
        if stale:
            restore.append(item.tag)
    return restore
