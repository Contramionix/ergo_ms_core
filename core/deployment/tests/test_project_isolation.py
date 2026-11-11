from __future__ import annotations

import json
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
import sys
from unittest.mock import MagicMock, patch

import _bootstrap  # noqa: F401
import yaml

from project_isolation import IsolationError, validate_django, validate_project


class ProjectIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        directory = self.root / 'virtual_env/pilot'
        directory.mkdir(parents=True)
        self.manifest = {
            'schema_version': 1,
            'pilot_id': 'isolated_test',
            'compose_project': 'isolated_test',
            'database': {
                'name': 'isolated_test', 'user': 'isolated_test',
                'endpoints': [['127.0.0.1', 15440], ['postgres', 5432]],
            },
            'redis': {'endpoints': [['127.0.0.1', 16380], ['redis', 6379]]},
        }
        (directory / 'isolation.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        (directory / 'identity').write_text('isolated_test', encoding='utf-8')
        (self.root / '.env').write_text(
            'ERGO_PILOT_MANIFEST=virtual_env/pilot/isolation.json\nERGO_DB=postgres\n'
            'ERGO_RUNTIME=docker\nDOCKER_COMPOSE_PROJECT=isolated_test\nAPI_DATABASE_CONN_MAX_AGE=0\n', encoding='utf-8',
        )
        self.sections = {'default': {
            'engine': 'postgresql', 'name': 'isolated_test', 'user': 'isolated_test',
            'password': 'NeverPrintThisSecret', 'host': '127.0.0.1', 'port': 15440,
        }}
        self._write_sections()

    def _write_sections(self):
        (self.root / 'databases.yaml').write_text(yaml.safe_dump({'databases': self.sections}), encoding='utf-8')

    def test_version_two_uses_declared_environment_constraints(self):
        self.manifest.update(schema_version=2, environment={'ERGO_RUNTIME': 'docker', 'API_DATABASE_CONN_MAX_AGE': '0'})
        path = self.root / 'virtual_env/pilot/isolation.json'
        path.write_text(json.dumps(self.manifest), encoding='utf-8')
        self.assertIsNotNone(validate_project(self.root, environ={}))
        with self.assertRaises(IsolationError):
            validate_project(self.root, environ={'API_DATABASE_CONN_MAX_AGE': '10'})

    def test_invalid_manifest_shapes_are_controlled_errors_without_credentials(self):
        path = self.root / 'virtual_env/pilot/isolation.json'
        for change in ({'schema_version': True}, {'database': []}, {'redis': {'endpoints': [None]}},
                       {'schema_version': 2, 'environment': {}}, {'database': {'name': 'working'}}):
            path.write_text(json.dumps({**self.manifest, **change}), encoding='utf-8')
            with self.subTest(change=change), self.assertRaises(IsolationError) as caught:
                validate_project(self.root, environ={})
            self.assertNotIn('NeverPrintThisSecret', str(caught.exception))

    def test_duplicate_yaml_keys_do_not_hide_an_unchecked_connection(self):
        (self.root / 'databases.yaml').write_text('databases: {}\ndatabases: {}\n', encoding='utf-8')
        with self.assertRaises(IsolationError):
            validate_project(self.root, environ={})

    def test_valid_profile_and_composed_container_endpoint(self):
        self.assertEqual(validate_project(self.root, environ={})['pilot_id'], 'isolated_test')
        self.sections['default']['host'] = 'postgres'
        self.sections['default']['port'] = 5432
        self._write_sections()
        self.assertIsNotNone(validate_project(self.root, environ={}))

    def test_rejects_working_database_in_any_alias(self):
        self.sections['celery_worker'] = {**self.sections['default'], 'name': 'ergo_ms'}
        self._write_sections()
        with self.assertRaises(IsolationError) as caught:
            validate_project(self.root, environ={})
        self.assertNotIn('NeverPrintThisSecret', str(caught.exception))

    def test_rejects_working_endpoint_even_with_pilot_database_name(self):
        self.sections['default']['port'] = 5432
        self._write_sections()
        with self.assertRaises(IsolationError):
            validate_project(self.root, environ={})

    def test_rejects_external_media_and_database_override(self):
        for overrides in (
            {'MEDIA_STORAGE_PATH': str(self.root.parent / 'working-media')},
            {'ERGO_DATABASES_YAML': str(self.root.parent / 'working.yaml')},
            {'CELERY_BROKER_URL': 'redis://working.example:6379/2'},
            {'BRIDGE_SERVICE_URLS': 'provider=http://working.example'},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(IsolationError):
                validate_project(self.root, environ=overrides)

    def test_checks_root_yaml_even_when_override_is_valid(self):
        override = self.root / 'virtual_env/pilot/databases.yaml'
        override.write_text(yaml.safe_dump({'databases': self.sections}), encoding='utf-8')
        self.sections['default']['name'] = 'ergo_ms'
        self._write_sections()
        with self.assertRaises(IsolationError):
            validate_project(self.root, environ={'ERGO_DATABASES_YAML': str(override)})

    def test_rejects_actual_django_alias_outside_profile(self):
        settings = SimpleNamespace(MEDIA_ROOT=str(self.root / 'media'), DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.postgresql', 'HOST': '127.0.0.1', 'PORT': '5432',
                'NAME': 'ergo_ms', 'USER': 'isolated_test',
            },
        })
        with patch.dict('os.environ', {}, clear=True), self.assertRaises(IsolationError):
            validate_django(self.root, settings)

    def test_requires_profile_for_pilot_only_commands(self):
        (self.root / '.env').write_text('', encoding='utf-8')
        (self.root / 'virtual_env/pilot/identity').unlink()
        (self.root / 'virtual_env/pilot/isolation.json').unlink()
        self.assertIsNone(validate_project(self.root, environ={}))
        with self.assertRaises(IsolationError):
            validate_project(self.root, environ={}, required=True)

    def test_existing_pilot_cannot_disable_its_manifest_pointer(self):
        (self.root / '.env').write_text('', encoding='utf-8')
        with self.assertRaises(IsolationError):
            validate_project(self.root, environ={})

    def test_pilot_cannot_disable_compose_validation_by_switching_runtime(self):
        with self.assertRaises(IsolationError):
            validate_project(self.root, environ={'ERGO_RUNTIME': 'host', 'DOCKER_COMPOSE_PROJECT': 'working'})

    def test_pilot_rejects_persistent_asgi_database_connections(self):
        with self.assertRaises(IsolationError):
            validate_project(self.root, environ={'API_DATABASE_CONN_MAX_AGE': '60'})

    def test_rejects_mismatched_identity_marker(self):
        (self.root / 'virtual_env/pilot/identity').write_text('another-pilot', encoding='utf-8')
        with self.assertRaises(IsolationError):
            validate_project(self.root, environ={})

    def test_rejects_a_different_compose_project(self):
        environment = {'ERGO_RUNTIME': 'docker', 'DOCKER_COMPOSE_PROJECT': 'isolated_test'}
        self.assertIsNotNone(validate_project(self.root, environ=environment))
        for key in ('DOCKER_COMPOSE_PROJECT', 'COMPOSE_PROJECT_NAME'):
            with self.subTest(key=key), self.assertRaises(IsolationError):
                validate_project(self.root, environ={**environment, key: 'working_system'})

    def test_loadtest_clone_never_terminates_source_connections(self):
        path = Path(__file__).resolve().parents[1] / 'loadtest/isolated_db.py'
        spec = importlib.util.spec_from_file_location('pilot_isolated_db_test', path)
        module = importlib.util.module_from_spec(spec)
        connection = MagicMock()
        manager = MagicMock()
        manager.__enter__.return_value = connection
        with patch.dict(sys.modules, {spec.name: module}):
            spec.loader.exec_module(module)
            config = module.DefaultDbConfig('postgresql', 'source', 'owner', 'secret', '127.0.0.1', 15440)
            with patch.object(module, '_connect_admin', return_value=manager), patch.object(
                module, '_terminate_db_backends',
            ) as terminate:
                self.assertEqual(module.refresh_clone(config), 'source_loadtest')
        terminate.assert_called_once_with(connection, 'source_loadtest')


if __name__ == '__main__':
    unittest.main()
