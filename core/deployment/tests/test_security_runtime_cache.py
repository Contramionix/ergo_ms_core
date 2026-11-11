import importlib.util
from pathlib import Path
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401

from security.catalog import DEFAULT_PROFILES_PATH, load_security_catalog


class SecurityRuntimeCacheTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[3]
        paths = ModuleType('src.config.paths')
        paths.DEPLOYMENT_DIR = root / 'core/deployment'
        spec = importlib.util.spec_from_file_location(
            'pilot_test_security_runtime', root / 'core/api/src/config/security_profile_runtime.py')
        self.runtime = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'src.config.paths': paths}):
            spec.loader.exec_module(self.runtime)

    def test_reuses_parsed_policy_but_reflects_environment_changes(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(
                self.runtime, 'load_security_catalog', wraps=load_security_catalog) as loader:
            first = self.runtime.merged_security_env()
            first['API_CSP_MODE'] = 'tampered'
            self.assertEqual(self.runtime.merged_security_env()['API_CSP_MODE'], 'as_is')
            self.assertEqual(loader.call_count, 1)
            with patch.dict('os.environ', {'ERGO_SECURITY': 'maximum'}):
                self.assertEqual(self.runtime.merged_security_env()['API_CSP_MODE'], 'no_unsafe_plus_externals')
            with patch.dict('os.environ', {'API_CSP_MODE': 'no_unsafe'}):
                self.assertEqual(self.runtime.merged_security_env()['API_CSP_MODE'], 'no_unsafe')

    def test_file_replacement_invalidates_cache_and_missing_policy_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / 'profiles.yaml'
            original = DEFAULT_PROFILES_PATH.read_text(encoding='utf-8')
            policy.write_text(original, encoding='utf-8')
            def load_policy():
                return load_security_catalog(policy)

            with patch.object(self.runtime, 'DEFAULT_PROFILES_PATH', policy), patch.dict(
                    'os.environ', {}, clear=True), patch.object(
                    self.runtime, 'load_security_catalog', side_effect=load_policy) as loader, patch(
                    'security.profile_defaults.load_security_catalog', side_effect=load_policy):
                self.assertEqual(self.runtime.merged_security_env()['API_THROTTLE_RATES_LOGIN'], '5/minute')
                policy.write_text(original.replace('standard: 5/minute', 'standard: 6/minute', 1), encoding='utf-8')
                self.assertEqual(self.runtime.merged_security_env()['API_THROTTLE_RATES_LOGIN'], '6/minute')
                self.assertEqual(loader.call_count, 2)
                policy.unlink()
                with self.assertRaises(FileNotFoundError):
                    self.runtime.merged_security_env()
