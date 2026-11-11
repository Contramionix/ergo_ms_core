"""Карантин очереди: классификатор ошибок и ключи Redis."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

_API_SRC = Path(__file__).resolve().parents[2] / 'api'
if str(_API_SRC) not in sys.path:
    sys.path.insert(0, str(_API_SRC))

from celery_balance.cluster import list_quarantine, release_quarantine  # noqa: E402
from src.core.utils.celery.cluster_quarantine import (  # noqa: E402
    RequiresPrimaryNode,
    is_local_resource_error,
    next_requeue_headers,
    requeue_count,
    should_requeue,
)


class _Redis:
    def __init__(self) -> None:
        self.store = {
            'celery_balance:quarantine:kept': json.dumps({
                'queue': 'kept',
                'reason': 'FileNotFoundError',
                'node_id': 'worker',
                'ts': '2026-01-01T00:00:00+00:00',
            }),
            'celery_balance:quarantine:other': json.dumps({'reason': 'ModuleNotFoundError'}),
        }

    def scan_iter(self, match=None):
        prefix = (match or '').rstrip('*')
        return [key for key in self.store if key.startswith(prefix)]

    def mget(self, keys):
        return [self.store.get(key) for key in keys]

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed


class LocalResourceTests(unittest.TestCase):
    def test_missing_file_module_and_primary_marker(self) -> None:
        self.assertTrue(is_local_resource_error(FileNotFoundError('model.bin')))
        self.assertTrue(is_local_resource_error(NotADirectoryError('dump')))
        self.assertTrue(is_local_resource_error(ModuleNotFoundError('missing_pkg')))
        self.assertTrue(is_local_resource_error(RequiresPrimaryNode('weights')))

    def test_loopback_refusal_counts_nested_cause(self) -> None:
        cause = ConnectionRefusedError(111, 'Connection refused', '127.0.0.1')
        wrapped = RuntimeError('task failed')
        wrapped.__cause__ = cause
        self.assertTrue(is_local_resource_error(wrapped))
        remote = ConnectionRefusedError(111, 'Connection refused')
        self.assertFalse(is_local_resource_error(remote))
        self.assertFalse(is_local_resource_error(RuntimeError('plain')))

    def test_requeue_stops_after_three(self) -> None:
        self.assertTrue(should_requeue(None))
        headers = next_requeue_headers(None)
        self.assertEqual(requeue_count(headers), 1)
        headers = next_requeue_headers(headers)
        headers = next_requeue_headers(headers)
        self.assertEqual(requeue_count(headers), 3)
        self.assertFalse(should_requeue(headers))


class QuarantineRedisTests(unittest.TestCase):
    def test_list_and_release(self) -> None:
        client = _Redis()
        rows = list_quarantine(client)
        self.assertEqual([item['queue'] for item in rows], ['kept', 'other'])
        self.assertEqual(rows[0]['reason'], 'FileNotFoundError')
        self.assertEqual(release_quarantine(client, 'kept'), 1)
        self.assertEqual(len(list_quarantine(client)), 1)
        self.assertEqual(release_quarantine(client, None), 1)
        self.assertEqual(list_quarantine(client), [])


if __name__ == '__main__':
    unittest.main()
