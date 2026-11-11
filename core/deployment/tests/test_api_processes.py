"""API_PROCESSES: общий кэш и то, какие порты попадают в nginx."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from api_processes import listen_ports, process_count, upstream_servers
from render_common import build_docker_upstream_blocks, build_host_upstream_blocks


class ApiProcessTests(unittest.TestCase):
    def test_single_process_without_shared_state(self) -> None:
        self.assertEqual(process_count({'API_PROCESSES': '4'}), 1)
        self.assertEqual(
            process_count({
                'API_PROCESSES': '4',
                'API_CACHE_BACKEND': 'locmem',
                'CHANNEL_LAYER_BACKEND': 'memory',
            }),
            1,
        )

    def test_explicit_count_when_cache_and_channel_are_shared(self) -> None:
        values = {
            'API_PROCESSES': '3',
            'API_CACHE_BACKEND': 'file',
            'CHANNEL_LAYER_BACKEND': 'postgres',
        }
        self.assertEqual(process_count(values), 3)
        self.assertEqual(
            listen_ports(values, base_port=8000),
            [8000, 8001, 8004],
        )

    def test_auto_uses_cpu_cap(self) -> None:
        values = {'REDIS_ENABLED': 'true', 'API_PROCESSES': 'auto'}
        self.assertEqual(process_count(values, cpu_count=2), 2)
        self.assertEqual(process_count(values, cpu_count=32), 8)

    def test_remote_upstream_stays_one_address_on_auto(self) -> None:
        values = {
            'API_PORT': '8000',
            'MEDIA_API_BIND_PORT': '8003',
            'NGINX_API_UPSTREAM': '10.0.0.2:8000',
            'REDIS_ENABLED': 'true',
            'API_PROCESSES': 'auto',
        }
        host_api, _media = build_host_upstream_blocks(values)
        self.assertIn('server 10.0.0.2:8000;', host_api)
        self.assertNotIn('10.0.0.2:8001', host_api)

    def test_remote_upstream_expands_when_count_is_explicit(self) -> None:
        values = {
            'API_PORT': '8000',
            'MEDIA_API_BIND_PORT': '8003',
            'NGINX_API_UPSTREAM': '10.0.0.2:8000',
            'REDIS_ENABLED': 'true',
            'API_PROCESSES': '2',
        }
        host_api, _media = build_host_upstream_blocks(values)
        self.assertIn('server 10.0.0.2:8000;', host_api)
        self.assertIn('server 10.0.0.2:8001;', host_api)

    def test_docker_upstream_lists_each_process(self) -> None:
        values = {
            'API_PORT': '8000',
            'MEDIA_API_BIND_PORT': '8003',
            'DOCKER_SERVICE_API': 'api',
            'DOCKER_SERVICE_MEDIA': 'media-api',
            'REDIS_ENABLED': 'true',
            'API_PROCESSES': '2',
        }
        api, _media = build_docker_upstream_blocks(values)
        self.assertIn('server api:8000;', api)
        self.assertIn('server api:8001;', api)
        self.assertIn('keepalive 32;', api)

    def test_local_upstream_servers(self) -> None:
        values = {'REDIS_ENABLED': 'true', 'API_PROCESSES': '2'}
        self.assertEqual(
            upstream_servers('127.0.0.1', values, base_port=8000),
            ['127.0.0.1:8000', '127.0.0.1:8001'],
        )
