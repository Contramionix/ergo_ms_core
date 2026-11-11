"""Возврат незакрытых задач: решение без Redis."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from celery_requeue.cmdline import classify_worker_argv  # noqa: E402
from celery_requeue.consumers import LocalConsumers, resolve_live_queues  # noqa: E402
from celery_requeue.decide import STALE_SEC, HeldTask, tags_to_restore  # noqa: E402


def _held(*pairs: tuple[str, str]) -> list[HeldTask]:
    return [HeldTask(tag, queue) for tag, queue in pairs]


class TagsToRestoreTests(unittest.TestCase):
    def test_no_consumer_returns_even_fresh_heartbeat(self) -> None:
        now = 1_000.0
        tags = tags_to_restore(
            _held(('a', 'hh_dump')),
            {'a': now - 5},
            set(),
            now,
        )
        self.assertEqual(tags, ['a'])

    def test_live_queue_keeps_fresh_heartbeat(self) -> None:
        now = 1_000.0
        tags = tags_to_restore(
            _held(('a', 'ai_assistant')),
            {'a': now - 5},
            {'ai_assistant'},
            now,
        )
        self.assertEqual(tags, [])

    def test_live_queue_returns_stale_heartbeat(self) -> None:
        now = 1_000.0
        tags = tags_to_restore(
            _held(('dead', 'hh_vpn'), ('live', 'hh_vpn')),
            {'dead': now - STALE_SEC, 'live': now - 5},
            {'hh_vpn'},
            now,
        )
        self.assertEqual(tags, ['dead'])

    def test_unknown_consumers_keep_tasks_without_stale_heartbeat(self) -> None:
        now = 1_000.0
        tags = tags_to_restore(
            _held(('fresh', 'hh_dump'), ('none', 'hh_dump'), ('old', 'catalog')),
            {'fresh': now - 5, 'old': now - STALE_SEC - 1},
            None,
            now,
        )
        self.assertEqual(tags, ['old'])

    def test_missing_heartbeat_on_live_queue_is_kept(self) -> None:
        tags = tags_to_restore(
            _held(('new', 'hh_selenium')),
            {},
            {'hh_selenium'},
            1_000.0,
        )
        self.assertEqual(tags, [])


class WorkerArgvTests(unittest.TestCase):
    def test_reads_queue_list(self) -> None:
        argv = [
            'python', '-m', 'celery', '-A', 'src', 'worker',
            '--hostname=hh_dump_worker', '-Q', 'hh_dump,hh_archive',
        ]
        classified = classify_worker_argv(argv)
        self.assertTrue(classified.is_worker)
        self.assertEqual(classified.queues, frozenset({'hh_dump', 'hh_archive'}))

    def test_worker_without_queues_is_uncertain(self) -> None:
        classified = classify_worker_argv(['python', '-m', 'celery', 'worker'])
        self.assertTrue(classified.is_worker)
        self.assertIsNone(classified.queues)

    def test_beat_is_not_a_worker(self) -> None:
        classified = classify_worker_argv(['python', '-m', 'celery', 'beat'])
        self.assertFalse(classified.is_worker)

    def test_queues_equals_form(self) -> None:
        classified = classify_worker_argv(
            ['python', '-m', 'celery', 'worker', '--queues=fgos,profstandart'],
        )
        self.assertEqual(classified.queues, frozenset({'fgos', 'profstandart'}))


class LiveQueuesTests(unittest.TestCase):
    def test_swarm_down_and_no_local_workers_is_empty(self) -> None:
        local = LocalConsumers(frozenset(), False, False)
        live = resolve_live_queues(local, None, cluster_on=True, swarm_down=True)
        self.assertEqual(live, set())

    def test_cluster_without_inspect_and_swarm_is_unknown(self) -> None:
        local = LocalConsumers(frozenset(), False, False)
        live = resolve_live_queues(local, None, cluster_on=True, swarm_down=False)
        self.assertIsNone(live)

    def test_uncertain_local_worker_hides_everyone(self) -> None:
        local = LocalConsumers(frozenset({'hh_dump'}), True, True)
        live = resolve_live_queues(local, {'ai_assistant'}, cluster_on=False, swarm_down=True)
        self.assertIsNone(live)

    def test_local_and_inspect_are_joined(self) -> None:
        local = LocalConsumers(frozenset({'hh_dump'}), False, True)
        live = resolve_live_queues(local, {'ai_assistant'}, cluster_on=False, swarm_down=True)
        self.assertEqual(live, {'hh_dump', 'ai_assistant'})


if __name__ == '__main__':
    unittest.main()
