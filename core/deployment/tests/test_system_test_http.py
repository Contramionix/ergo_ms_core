from __future__ import annotations

import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401

from system_test.http import wait_http  # noqa: E402


class SystemHttpReadinessTests(unittest.TestCase):
    def test_readiness_retries_until_success(self) -> None:
        with patch('system_test.http.http_status', side_effect=[503, 200]) as probe, \
                patch('system_test.http.time.sleep'), \
                patch('system_test.http.time.monotonic', side_effect=[0, 0, 1]):
            wait_http('http://127.0.0.1:18000', path='/api/system/ready/', expected_status=200)
        self.assertEqual(probe.call_count, 2)

    def test_error_responses_do_not_mark_api_ready(self) -> None:
        for status in (0, 400, 404, 500, 503):
            with self.subTest(status=status), \
                    patch('system_test.http.http_status', return_value=status), \
                    patch('system_test.http.time.sleep'), \
                    patch('system_test.http.time.monotonic', side_effect=[0, 0, 2]):
                with self.assertRaisesRegex(RuntimeError, f'status={status}'):
                    wait_http('http://127.0.0.1:18000', timeout_sec=1,
                              path='/api/system/ready/', expected_status=200)

    def test_generic_probe_still_accepts_authentication_required(self) -> None:
        with patch('system_test.http.http_status', return_value=401):
            wait_http('http://127.0.0.1:18000')


if __name__ == '__main__':
    unittest.main()
