"""Кластерный план Celery: доли очередей, placement, стек Swarm."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import _bootstrap  # noqa: F401

from celery_balance.cluster_plan import (  # noqa: E402
    NodePlan,
    NodeView,
    apply_cluster_share,
    plan_cluster,
)
from celery_balance.constants import (  # noqa: E402
    CLASS_HEAVY,
    CLASS_LIGHT,
    CLASS_MEDIUM,
    PLACEMENT_AGENT,
    PLACEMENT_ANY,
    PLACEMENT_AUTO,
    PLACEMENT_GPU,
    PLACEMENT_PRIMARY,
)
from celery_balance.footprint_loader import (  # noqa: E402
    FootprintCatalog,
    TaskFootprint,
    _parse_task,
)
from celery_balance.planner import WorkerPlan  # noqa: E402
from packages.models import PackageSource  # noqa: E402
from packages.registry import _parse_package  # noqa: E402
from celery_balance.settings import load_settings  # noqa: E402
from generate_swarm_stack import render_stack  # noqa: E402


def _node(
    node_id: str,
    *,
    primary: bool,
    ram: float = 8000,
    cpu: float = 8,
    gpu: bool = False,
    vram: float = 0,
    egress_ok: bool = True,
) -> NodeView:
    devices = ((0, vram),) if gpu else ()
    return NodeView(
        node_id=node_id,
        primary=primary,
        celery_ram_budget_mb=ram,
        celery_cpu_budget=cpu,
        cpu_count=cpu,
        gpu_available=gpu,
        vram_free_mb=vram,
        utilization_pct=0,
        devices=devices,
        egress_ok=egress_ok,
    )


def _spec(queue: str, **kwargs) -> TaskFootprint:
    values = dict(
        queue=queue,
        pattern='',
        task_class=CLASS_HEAVY,
        ram_mb=512,
        cpu_units=1,
        gpu_required=False,
        vram_mb=0,
        max_parallel=4,
        cpu_fallback=True,
        module='sample',
        placement=PLACEMENT_ANY,
    )
    values.update(kwargs)
    return TaskFootprint(**values)


def _catalog(*specs: TaskFootprint) -> FootprintCatalog:
    return FootprintCatalog(tasks=specs, by_queue={item.queue: item for item in specs})


def _settings():
    from celery_balance.settings import BalanceSettings

    return BalanceSettings(
        mode='auto',
        os_reserve_ram_mb=0,
        reserve_cpu=0,
        min_concurrency=1,
        max_concurrency=None,
        gpu_enabled=True,
        gpu_util_cap=80,
        watch_interval_sec=30,
        hysteresis_ratio=0.2,
        cluster='on',
        cluster_role='manager',
        node_id='primary',
        node_ttl_sec=90,
    )


class ClusterPlanTests(unittest.TestCase):
    def test_any_queue_splits_across_two_nodes(self) -> None:
        plans = plan_cluster(
            [_node('primary', primary=True), _node('worker', primary=False)],
            all_queues=['sample_q'],
            catalog=_catalog(_spec('sample_q', max_parallel=4)),
            settings=_settings(),
            depths={},
            history={},
        )
        by_id = {item.node_id: item for item in plans}
        self.assertEqual(
            by_id['primary'].queue_limits['sample_q'] + by_id['worker'].queue_limits['sample_q'],
            4,
        )
        self.assertGreater(by_id['primary'].queue_limits['sample_q'], 0)
        self.assertGreater(by_id['worker'].queue_limits['sample_q'], 0)

    def test_missing_node_keeps_the_whole_share(self) -> None:
        plans = plan_cluster(
            [_node('primary', primary=True)],
            all_queues=['sample_q'],
            catalog=_catalog(_spec('sample_q', placement=PLACEMENT_ANY, max_parallel=4)),
            settings=_settings(),
            depths={},
            history={},
        )
        self.assertEqual(plans[0].queue_limits['sample_q'], 4)

    def test_primary_placement_stays_on_primary(self) -> None:
        plans = plan_cluster(
            [_node('primary', primary=True), _node('worker', primary=False)],
            all_queues=['sample_q'],
            catalog=_catalog(_spec('sample_q', placement=PLACEMENT_PRIMARY, max_parallel=3)),
            settings=_settings(),
            depths={},
            history={},
        )
        by_id = {item.node_id: item for item in plans}
        self.assertEqual(by_id['primary'].queue_limits['sample_q'], 3)
        self.assertNotIn('sample_q', by_id['worker'].queues)

    def test_gpu_queue_skips_node_without_card(self) -> None:
        plans = plan_cluster(
            [
                _node('primary', primary=True, gpu=False),
                _node('worker', primary=False, gpu=True, vram=8192),
            ],
            all_queues=['sample_q'],
            catalog=_catalog(_spec(
                'sample_q',
                placement=PLACEMENT_GPU,
                gpu_required=True,
                vram_mb=4096,
                cpu_fallback=False,
                max_parallel=2,
            )),
            settings=_settings(),
            depths={},
            history={},
        )
        by_id = {item.node_id: item for item in plans}
        self.assertNotIn('sample_q', by_id['primary'].queues)
        self.assertEqual(by_id['worker'].queue_limits['sample_q'], 2)

    def test_small_node_keeps_a_slot_when_ceiling_allows(self) -> None:
        from celery_balance.cluster_plan import _split

        self.assertEqual(_split(2, [100, 5]), [1, 1])

    def test_share_lowers_local_limit(self) -> None:
        from celery_balance.cluster_plan import NodePlan

        local = WorkerPlan(
            name='all',
            hostname='all',
            queues=['sample_q'],
            pool='threads',
            yaml_concurrency=8,
            concurrency=4,
            prefetch_multiplier=1,
            autoscale_min=None,
            autoscale_max=None,
            gpu_required=False,
            queue_limits={'sample_q': 4},
        )
        apply_cluster_share(
            [local],
            NodePlan(
                node_id='primary',
                primary=True,
                queues=['sample_q'],
                concurrency=1,
                prefetch_multiplier=1,
                queue_limits={'sample_q': 1},
                queue_classes={},
                pause_queues=[],
            ),
        )
        self.assertEqual(local.queue_limits['sample_q'], 1)

    def test_agent_queue_goes_to_worker_and_primary_stays_paused(self) -> None:
        plans = plan_cluster(
            [_node('primary', primary=True), _node('worker', primary=False)],
            all_queues=['sample_q'],
            catalog=_catalog(_spec('sample_q', placement=PLACEMENT_AGENT, max_parallel=4)),
            settings=_settings(),
            depths={},
            history={},
        )
        by_id = {item.node_id: item for item in plans}
        self.assertEqual(by_id['worker'].queue_limits['sample_q'], 4)
        self.assertNotIn('sample_q', by_id['primary'].queue_limits)
        self.assertIn('sample_q', by_id['primary'].queues)
        self.assertIn('sample_q', by_id['primary'].pause_queues)
        local = WorkerPlan(
            name='all',
            hostname='all',
            queues=['sample_q'],
            pool='threads',
            yaml_concurrency=4,
            concurrency=4,
            prefetch_multiplier=1,
            autoscale_min=None,
            autoscale_max=None,
            gpu_required=False,
            queue_limits={'sample_q': 4},
        )
        apply_cluster_share([local], by_id['primary'])
        self.assertEqual(local.queue_limits['sample_q'], 0)
        self.assertIn('sample_q', local.pause_queues)

    def test_agent_queue_falls_back_to_primary(self) -> None:
        plans = plan_cluster(
            [_node('primary', primary=True)],
            all_queues=['sample_q'],
            catalog=_catalog(_spec('sample_q', placement=PLACEMENT_AGENT, max_parallel=4)),
            settings=_settings(),
            depths={},
            history={},
        )
        self.assertEqual(plans[0].queue_limits['sample_q'], 4)
        self.assertNotIn('sample_q', plans[0].pause_queues)

    def test_agent_queue_stays_local_until_image_is_ready(self) -> None:
        plans = plan_cluster(
            [_node('primary', primary=True), _node('worker', primary=False)],
            all_queues=['sample_q'],
            catalog=_catalog(_spec('sample_q', placement=PLACEMENT_AGENT, max_parallel=4)),
            settings=_settings(),
            depths={},
            history={},
            agent_ready=False,
        )
        by_id = {item.node_id: item for item in plans}
        self.assertEqual(by_id['primary'].queue_limits['sample_q'], 4)
        self.assertNotIn('sample_q', by_id['worker'].queues)
        self.assertNotIn('sample_q', by_id['primary'].pause_queues)

    def test_agent_takes_the_queue_while_it_is_up(self) -> None:
        plans = plan_cluster(
            [
                _node('primary', primary=True, ram=80000, cpu=16),
                _node('worker', primary=False, ram=80000, cpu=2),
            ],
            all_queues=['sample_q'],
            catalog=_catalog(_spec(
                'sample_q',
                placement=PLACEMENT_AGENT,
                max_parallel=50,
                ram_mb=768,
            )),
            settings=_settings(),
            depths={},
            history={},
        )
        by_id = {item.node_id: item for item in plans}
        self.assertEqual(by_id['worker'].queue_limits['sample_q'], 2)
        self.assertNotIn('sample_q', by_id['primary'].queue_limits)
        self.assertIn('sample_q', by_id['primary'].pause_queues)

    def test_agent_without_egress_stays_on_primary(self) -> None:
        plans = plan_cluster(
            [
                _node('primary', primary=True),
                _node('worker', primary=False, egress_ok=False),
            ],
            all_queues=['sample_q'],
            catalog=_catalog(_spec(
                'sample_q',
                placement=PLACEMENT_AGENT,
                needs_network=True,
                max_parallel=4,
            )),
            settings=_settings(),
            depths={},
            history={},
        )
        by_id = {item.node_id: item for item in plans}
        self.assertEqual(by_id['primary'].queue_limits['sample_q'], 4)
        self.assertNotIn('sample_q', by_id['worker'].queues)
        self.assertNotIn('sample_q', by_id['primary'].pause_queues)

    def test_auto_medium_fills_the_worker_first(self) -> None:
        plans = plan_cluster(
            [_node('primary', primary=True), _node('worker', primary=False)],
            all_queues=['sample_q'],
            catalog=_catalog(_spec(
                'sample_q',
                placement=PLACEMENT_AUTO,
                task_class=CLASS_MEDIUM,
                max_parallel=4,
            )),
            settings=_settings(),
            depths={},
            history={},
        )
        by_id = {item.node_id: item for item in plans}
        self.assertEqual(by_id['worker'].queue_limits['sample_q'], 4)
        self.assertNotIn('sample_q', by_id['worker'].pause_queues)
        self.assertIn('sample_q', by_id['primary'].pause_queues)

    def test_auto_light_and_gpu_stay_on_primary(self) -> None:
        nodes = [_node('primary', primary=True), _node('worker', primary=False, gpu=True, vram=8000)]
        for task_class, gpu_required in ((CLASS_LIGHT, False), (CLASS_HEAVY, True)):
            plans = plan_cluster(
                nodes,
                all_queues=['sample_q'],
                catalog=_catalog(_spec(
                    'sample_q',
                    placement=PLACEMENT_AUTO,
                    task_class=task_class,
                    gpu_required=gpu_required,
                    max_parallel=2,
                )),
                settings=_settings(),
                depths={},
                history={},
            )
            by_id = {item.node_id: item for item in plans}
            self.assertEqual(by_id['primary'].queue_limits['sample_q'], 2)
            self.assertNotIn('sample_q', by_id['worker'].queues)

    def test_auto_quarantine_stays_on_primary(self) -> None:
        plans = plan_cluster(
            [_node('primary', primary=True), _node('worker', primary=False)],
            all_queues=['sample_q'],
            catalog=_catalog(_spec('sample_q', placement=PLACEMENT_AUTO, task_class=CLASS_MEDIUM)),
            settings=_settings(),
            depths={},
            history={},
            quarantined={'sample_q'},
        )
        by_id = {item.node_id: item for item in plans}
        self.assertEqual(by_id['primary'].queue_limits['sample_q'], 4)
        self.assertNotIn('sample_q', by_id['worker'].queues)

    def test_auto_off_stays_on_primary(self) -> None:
        from dataclasses import replace

        plans = plan_cluster(
            [_node('primary', primary=True), _node('worker', primary=False)],
            all_queues=['sample_q'],
            catalog=_catalog(_spec('sample_q', placement=PLACEMENT_AUTO, task_class=CLASS_MEDIUM)),
            settings=replace(_settings(), auto_placement='off'),
            depths={},
            history={},
        )
        by_id = {item.node_id: item for item in plans}
        self.assertEqual(by_id['primary'].queue_limits['sample_q'], 4)
        self.assertNotIn('sample_q', by_id['worker'].queues)

    def test_auto_without_egress_stays_on_primary(self) -> None:
        plans = plan_cluster(
            [
                _node('primary', primary=True),
                _node('worker', primary=False, egress_ok=False),
            ],
            all_queues=['sample_q'],
            catalog=_catalog(_spec('sample_q', placement=PLACEMENT_AUTO, task_class=CLASS_MEDIUM)),
            settings=_settings(),
            depths={},
            history={},
        )
        by_id = {item.node_id: item for item in plans}
        self.assertEqual(by_id['primary'].queue_limits['sample_q'], 4)
        self.assertNotIn('sample_q', by_id['worker'].queues)


class PlacementParseTests(unittest.TestCase):
    def test_default_placement_is_auto(self) -> None:
        parsed = _parse_task(
            {'queue': 'sample_q'},
            module='sample',
            defaults={},
            path=Path('task_footprint.yaml'),
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.placement, PLACEMENT_AUTO)

    def test_unknown_placement_falls_back(self) -> None:
        parsed = _parse_task(
            {'queue': 'sample_q', 'placement': 'both'},
            module='sample',
            defaults={},
            path=Path('task_footprint.yaml'),
        )
        assert parsed is not None
        self.assertEqual(parsed.placement, PLACEMENT_AUTO)

    def test_explicit_auto_parses(self) -> None:
        parsed = _parse_task(
            {'queue': 'sample_q', 'placement': 'auto'},
            module='sample',
            defaults={},
            path=Path('task_footprint.yaml'),
        )
        assert parsed is not None
        self.assertEqual(parsed.placement, PLACEMENT_AUTO)


class EgressProbeTests(unittest.TestCase):
    def test_empty_url_skips_the_check(self) -> None:
        from celery_balance.egress import probe_egress

        self.assertTrue(probe_egress(''))

    def test_closed_port_is_not_egress(self) -> None:
        from celery_balance.egress import probe_egress

        self.assertFalse(probe_egress('http://127.0.0.1:1', timeout=0.5))


class ClusterSettingsTests(unittest.TestCase):
    def test_cluster_off_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.dict(os.environ, {'CELERY_CLUSTER': '', 'ERGO_NODE_ID': 'node-a'}, clear=False):
                os.environ.pop('CELERY_CLUSTER', None)
                os.environ.pop('CELERY_CLUSTER_AUTO_PLACEMENT', None)
                os.environ.pop('CELERY_CLUSTER_QUARANTINE_TTL', None)
                settings = load_settings(root)
        self.assertEqual(settings.cluster, 'off')
        self.assertFalse(settings.cluster_enabled)
        self.assertEqual(settings.node_id, 'node-a')
        self.assertEqual(settings.auto_placement, 'agent')
        self.assertEqual(settings.quarantine_ttl_sec, 7 * 24 * 3600)


class SwarmStackTests(unittest.TestCase):
    def test_stack_places_workers_and_optional_gpu(self) -> None:
        text = render_stack(
            image='registry.example/ergo-worker:local',
            manager_host='10.0.0.1',
            databases_file='/tmp/databases.yaml',
            env_file='/tmp/dotenv',
            gpu=True,
            db_port='5433',
        )
        data = yaml.safe_load(text)
        worker = data['services']['ergo-celery-worker']
        self.assertIn('node.labels.ergo.worker == true', worker['deploy']['placement']['constraints'])
        self.assertEqual(worker['deploy']['mode'], 'global')
        self.assertIn('NVIDIA-GPU', text)
        self.assertIn('ergo-celery-agent', data['services'])
        self.assertEqual(worker['environment']['REDIS_HOST'], '10.0.0.1')
        self.assertEqual(str(worker['environment']['ERGO_DOCKER_DB_PORT']), '5433')
        self.assertEqual(worker['networks'], ['host'])
        self.assertEqual(worker['stop_grace_period'], '60s')
        self.assertIn('/var/run/docker.sock', str(worker['volumes']))
        self.assertIn('ergo_worker_cache', text)
        self.assertIn('ergo_worker_packages', text)
        self.assertIn('prepare_swarm_packages.py', str(worker['command']))
        self.assertNotIn('vacancies_parser', text)
        agent = data['services']['ergo-celery-agent']
        self.assertNotIn('docker.sock', str(agent))

    def test_ollama_service_takes_the_gpu_and_configs_are_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dotenv = root / 'dotenv'
            databases = root / 'databases.yaml'
            dotenv.write_text('A=1\n', encoding='utf-8')
            databases.write_text('port: 1\n', encoding='utf-8')
            text = render_stack(
                image='registry.example/ergo-worker:local',
                manager_host='10.0.0.1',
                databases_file=str(databases),
                env_file=str(dotenv),
                gpu=True,
                media_url='http://10.0.0.1:8003',
                media_internal_key='test-media-key',
                ollama_service=True,
                ollama_bind='10.0.0.2:11434',
                ollama_image='registry.example/ollama:local',
            )
        data = yaml.safe_load(text)
        worker = data['services']['ergo-celery-worker']
        ollama = data['services']['ergo-ollama']
        self.assertNotIn('resources', worker['deploy'])
        self.assertEqual(ollama['environment']['OLLAMA_HOST'], '10.0.0.2:11434')
        self.assertEqual(
            worker['environment']['OLLAMA_BASE_URL_OVERRIDE'],
            'http://10.0.0.2:11434',
        )
        self.assertEqual(worker['environment']['MEDIA_API_INTERNAL_KEY'], 'test-media-key')
        self.assertIn('NVIDIA-GPU', str(ollama['deploy']))
        self.assertIn('ergo_ollama_models', data['volumes'])
        names = list(data['configs'])
        self.assertTrue(any(name.startswith('ergo_dotenv_') and name != 'ergo_dotenv' for name in names))

    def test_swarm_worker_flag_parses(self) -> None:
        spec = _parse_package(
            'browser',
            {'kind': 'custom', 'installer': 'install.py', 'swarm_worker': True},
            source=PackageSource.CORE,
        )
        self.assertIsNotNone(spec)
        self.assertTrue(spec.swarm_worker)
        plain = _parse_package(
            'plain',
            {'kind': 'custom', 'installer': 'install.py'},
            source=PackageSource.CORE,
        )
        self.assertFalse(plain.swarm_worker)


class WorkerImageTests(unittest.TestCase):
    def test_worker_stage_installs_cairo(self) -> None:
        dockerfile = Path(__file__).resolve().parents[1] / 'docker' / 'Dockerfile.python'
        text = dockerfile.read_text(encoding='utf-8')
        worker = text.split('FROM base AS worker', 1)[1].split('FROM base AS runtime', 1)[0]
        self.assertIn('libcairo2', worker)
        self.assertGreater(worker.find('poetry run pip install'), worker.find('libnss3'))
        self.assertGreater(worker.find('libcairo2'), worker.find('poetry run pip install'))


class DeclaredModuleQueueTests(unittest.TestCase):
    def test_workers_yaml_queues_join_the_plan(self) -> None:
        from celery_balance.workers import _names_from_workers_file

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'celery_workers.yaml'
            path.write_text(
                'workers:\n'
                '  vpn:\n'
                '    queues: [hh_vpn]\n'
                '  catalog:\n'
                '    queues: education_materials_catalog\n',
                encoding='utf-8',
            )
            self.assertEqual(
                _names_from_workers_file(path),
                {'hh_vpn', 'education_materials_catalog'},
            )
            self.assertEqual(_names_from_workers_file(Path(tmp) / 'missing.yaml'), set())


class PlanTtlAndLastPlanTests(unittest.TestCase):
    def test_default_plan_ttl_is_longer_than_node_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.env').write_text(
                'CELERY_CLUSTER=on\n'
                'CELERY_CLUSTER_NODE_TTL=90\n'
                'CELERY_BALANCE_WATCH_INTERVAL=30\n',
                encoding='utf-8',
            )
            with patch.dict(os.environ, {}, clear=False):
                for key in (
                    'CELERY_CLUSTER',
                    'CELERY_CLUSTER_NODE_TTL',
                    'CELERY_BALANCE_WATCH_INTERVAL',
                    'CELERY_CLUSTER_PLAN_TTL',
                ):
                    os.environ.pop(key, None)
                settings = load_settings(root)
            self.assertEqual(settings.node_ttl_sec, 90)
            self.assertGreaterEqual(settings.plan_ttl_sec, 600)
            self.assertGreaterEqual(settings.plan_ttl_sec, settings.node_ttl_sec * 2)

    def test_explicit_plan_ttl_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.env').write_text(
                'CELERY_CLUSTER=on\nCELERY_CLUSTER_PLAN_TTL=900\n',
                encoding='utf-8',
            )
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop('CELERY_CLUSTER_PLAN_TTL', None)
                self.assertEqual(load_settings(root).plan_ttl_sec, 900)

    def test_renew_plans_expires_existing_keys(self) -> None:
        from celery_balance.cluster import renew_plans
        from celery_balance.constants import PLAN_KEY_PREFIX

        class _Client:
            def __init__(self) -> None:
                self.expired: list[tuple[str, int]] = []

            def scan_iter(self, match: str = '*'):
                yield f'{PLAN_KEY_PREFIX}worker-a'
                yield f'{PLAN_KEY_PREFIX}worker-b'

            def expire(self, key: str, ttl: int) -> bool:
                self.expired.append((key, ttl))
                return True

        client = _Client()
        self.assertEqual(renew_plans(client, 600), 2)
        self.assertEqual(
            client.expired,
            [(f'{PLAN_KEY_PREFIX}worker-a', 600), (f'{PLAN_KEY_PREFIX}worker-b', 600)],
        )

    def test_missing_redis_plan_falls_back_to_last_plan(self) -> None:
        from celery_balance.cluster import resolve_allowed_queues, save_last_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.env').write_text(
                'CELERY_CLUSTER=on\n'
                'CELERY_CLUSTER_ROLE=agent\n'
                'ERGO_NODE_ID=agent-1\n',
                encoding='utf-8',
            )
            (root / 'virtual_env' / 'cache' / 'celery_balance').mkdir(parents=True)
            save_last_plan(
                root,
                {
                    'allowed_queues': ['education_materials_structure'],
                    'pause_queues': [],
                    'queue_limits': {},
                },
                node_id='agent-1',
            )
            with patch.dict(
                os.environ,
                {
                    'CELERY_CLUSTER': 'on',
                    'CELERY_CLUSTER_ROLE': 'agent',
                    'ERGO_NODE_ID': 'agent-1',
                },
                clear=False,
            ):
                with patch('celery_balance.cluster.connect', return_value=None):
                    queues = resolve_allowed_queues(root)
            self.assertEqual(queues, ['education_materials_structure'])

    def test_live_empty_redis_plan_is_not_replaced_by_cache(self) -> None:
        from celery_balance.cluster import resolve_allowed_queues, save_last_plan

        class _Client:
            def get(self, _key: str):
                import json

                return json.dumps({
                    'node_id': 'agent-1',
                    'allowed_queues': [],
                    'pause_queues': [],
                })

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.env').write_text(
                'CELERY_CLUSTER=on\n'
                'CELERY_CLUSTER_ROLE=agent\n'
                'ERGO_NODE_ID=agent-1\n',
                encoding='utf-8',
            )
            (root / 'virtual_env' / 'cache' / 'celery_balance').mkdir(parents=True)
            save_last_plan(
                root,
                {'allowed_queues': ['education_materials_structure'], 'pause_queues': []},
                node_id='agent-1',
            )
            with patch.dict(
                os.environ,
                {
                    'CELERY_CLUSTER': 'on',
                    'CELERY_CLUSTER_ROLE': 'agent',
                    'ERGO_NODE_ID': 'agent-1',
                },
                clear=False,
            ):
                with patch('celery_balance.cluster.connect', return_value=_Client()):
                    self.assertEqual(resolve_allowed_queues(root), [])

    def test_watch_cycle_survives_exception(self) -> None:
        from celery_balance import watch as watch_mod

        calls = {'n': 0}

        def _once(*_args, **_kwargs):
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError('boom')
            raise SystemExit(0)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.env').write_text('CELERY_CLUSTER=off\n', encoding='utf-8')
            with patch.object(watch_mod, '_watch_once', side_effect=_once):
                with patch.object(watch_mod, '_start_plan_keepalive'):
                    with patch.object(watch_mod.time, 'sleep', return_value=None):
                        with self.assertRaises(SystemExit):
                            watch_mod.run_watch(root, dry_run=True, as_json=False)
        self.assertGreaterEqual(calls['n'], 2)


if __name__ == '__main__':
    unittest.main()
