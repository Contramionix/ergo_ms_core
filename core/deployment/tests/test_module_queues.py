from __future__ import annotations

import sys
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

_API_DIR = Path(__file__).resolve().parents[2] / 'api'
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from src.core.utils.celery.module_queues import (  # noqa: E402
    dedicated_queue_names,
    generic_module_worker_needed,
    queues_for_module,
    read_dedicated_queues,
    read_module_workers,
)


class ModuleQueuesTests(unittest.TestCase):
    def test_includes_nested_app_queues(self) -> None:
        routes = {
            'modules.demo_mod.api.tasks.*': {'queue': 'demo_mod'},
            'modules.demo_mod.api.source.tasks.*': {'queue': 'source_q'},
            'modules.other.api.tasks.*': {'queue': 'other'},
        }
        missing = Path(self.id().replace('.', '_'))
        self.assertEqual(
            queues_for_module('demo_mod', routes=routes, module_dir=missing),
            ['demo_mod', 'source_q'],
        )

    def test_empty_name(self) -> None:
        self.assertEqual(queues_for_module(''), [])

    def test_catalog_name_always_included(self) -> None:
        routes = {
            'modules.demo_mod.api.source.tasks.*': {'queue': 'source_q'},
        }
        missing = Path(self.id().replace('.', '_'))
        self.assertEqual(
            queues_for_module('demo_mod', routes=routes, module_dir=missing),
            ['demo_mod', 'source_q'],
        )

    def test_reads_nested_celery_config_when_routes_empty(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            nested = root / 'roadmap_sh'
            nested.mkdir()
            (nested / 'celery_config.py').write_text(
                "class Cfg:\n"
                "    def get_task_routes(self):\n"
                "        return {'modules.demo_mod.api.roadmap_sh.tasks.*': {'queue': 'roadmap_sh'}}\n",
                encoding='utf-8',
            )
            self.assertEqual(
                queues_for_module('demo_mod', routes={}, module_dir=root),
                ['demo_mod', 'roadmap_sh'],
            )

    def test_dedicated_queues_stay_out_of_the_shared_list(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            module = root / 'demo_mod'
            module.mkdir()
            (module / 'dedicated_queues.yaml').write_text(
                'queues:\n'
                '  - name: file_load\n'
                '    hostname: file_load_worker\n'
                '    concurrency: 2\n',
                encoding='utf-8',
            )
            specs = read_dedicated_queues(module)
            self.assertEqual(
                specs,
                [{'name': 'file_load', 'hostname': 'file_load_worker', 'concurrency': 2}],
            )
            self.assertEqual(dedicated_queue_names(root), {'file_load'})
            shared = [
                name for name in ['demo_mod', 'file_load', 'site']
                if name not in {spec['name'] for spec in specs}
            ]
            self.assertEqual(shared, ['demo_mod', 'site'])

    def test_celery_workers_yaml_names_several_queues(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            module = Path(raw) / 'demo_mod'
            module.mkdir()
            (module / 'celery_workers.yaml').write_text(
                'workers:\n'
                '  - name: crawl\n'
                '    hostname: crawl_worker\n'
                '    queues: [site, files]\n'
                '    concurrency: 2\n',
                encoding='utf-8',
            )
            specs = read_module_workers(module)
            self.assertEqual(specs[0]['name'], 'crawl')
            self.assertEqual(specs[0]['queues'], ['site', 'files'])
            self.assertEqual(dedicated_queue_names(Path(raw)), {'site', 'files'})

    def test_legacy_dedicated_file_stays_a_worker(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            module = Path(raw) / 'demo_mod'
            module.mkdir()
            (module / 'dedicated_queues.yaml').write_text(
                'queues:\n'
                '  - name: file_load\n'
                '    hostname: file_load_worker\n'
                '    concurrency: 2\n',
                encoding='utf-8',
            )
            (module / 'celery_workers.yaml').write_text(
                'workers:\n'
                '  - name: crawl\n'
                '    hostname: crawl_worker\n'
                '    queues: [site]\n'
                '    concurrency: 1\n',
                encoding='utf-8',
            )
            names = [spec['name'] for spec in read_module_workers(module)]
            self.assertEqual(names, ['crawl', 'file_load'])
            self.assertEqual(dedicated_queue_names(Path(raw)), {'site', 'file_load'})

    def test_generic_worker_skipped_when_named_worker_owns_every_queue(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            module = Path(raw) / 'demo_mod'
            module.mkdir()
            (module / 'celery_config.py').write_text(
                'class Cfg:\n'
                '    def get_task_routes(self):\n'
                '        return {}\n',
                encoding='utf-8',
            )
            (module / 'celery_workers.yaml').write_text(
                'workers:\n'
                '  - name: demo_mod\n'
                '    hostname: demo_mod_worker\n'
                '    queues: [demo_mod]\n'
                '    concurrency: 1\n',
                encoding='utf-8',
            )
            self.assertFalse(generic_module_worker_needed('demo_mod', module))

            (module / 'celery_workers.yaml').write_text(
                'workers:\n'
                '  - name: crawl\n'
                '    hostname: crawl_worker\n'
                '    queues: [site]\n'
                '    concurrency: 1\n',
                encoding='utf-8',
            )
            self.assertTrue(generic_module_worker_needed('demo_mod', module))


if __name__ == '__main__':
    unittest.main()
