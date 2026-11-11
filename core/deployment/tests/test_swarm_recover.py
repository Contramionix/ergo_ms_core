"""Восстановление Swarm, если менеджер не занял порт."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from unittest.mock import patch

from swarm_runtime import _pid_alive, swarm_listen_recoverable  # noqa: E402


class SwarmListenRecoverTests(unittest.TestCase):
    def test_bind_error_with_address_is_recoverable(self) -> None:
        error = (
            'manager stopped: failed to listen on remote API address: '
            'listen tcp 10.0.0.1:2377: bind: cannot assign requested address'
        )
        self.assertTrue(swarm_listen_recoverable('error', error, True))

    def test_active_manager_is_not_restarted(self) -> None:
        self.assertFalse(swarm_listen_recoverable('active', '', True))

    def test_bind_error_without_address_waits(self) -> None:
        self.assertFalse(
            swarm_listen_recoverable('error', 'cannot assign requested address', False),
        )

    def test_other_swarm_error_is_left_alone(self) -> None:
        self.assertFalse(swarm_listen_recoverable('error', 'rpc error', True))

    def test_foreign_watch_counts_as_alive(self) -> None:
        with patch('swarm_runtime.os.kill', side_effect=PermissionError):
            self.assertTrue(_pid_alive(1))

    def test_missing_watch_counts_as_dead(self) -> None:
        with patch('swarm_runtime.os.kill', side_effect=ProcessLookupError):
            self.assertFalse(_pid_alive(1))


if __name__ == '__main__':
    unittest.main()
