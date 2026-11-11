from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import yaml
import _bootstrap  # noqa: F401

from lifecycle.context import DeploymentContext
from lifecycle.pipeline import DeploymentPipeline
from lifecycle.recipes import RECIPE_REGISTRY
from lifecycle.steps.runtime_requirements_steps import RuntimeRequirementsStep
from packages.models import PackageSource
from packages.registry import PackageRegistryError, discover_packages
from runtime_requirements import RuntimeRequirementsError, discover_requirements, load_manifest, model_entries, required_python_groups
from runtime_requirements.plan import install_required_tools, resolve_plan

ROOT = Path(__file__).resolve().parents[3]


class RuntimeRequirementsTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'virtual_env/cache/tmp'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base, prefix='test_runtime_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'pyproject.toml').write_text('[tool.poetry.group.analytics.dependencies]\n', encoding='utf-8')
        self.module = self.root / 'modules' / 'consumer'
        (self.module / 'api').mkdir(parents=True)
        self.env = patch.dict(os.environ, {'DISABLED_MODULES': '', 'MODULE_RUNTIME': 'monolith', 'ERGO_PROCESS_ROLE': '', 'PROCESS_MODULES': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def manifest(self, **kwargs):
        data = {'schema_version': 1, 'module': 'consumer', **kwargs}
        (self.module / 'runtime_requirements.yaml').write_text(yaml.safe_dump(data), encoding='utf-8')

    def test_common_tools_are_owned_by_core_without_loaded_provider_modules(self):
        packages = discover_packages(self.root)
        for name in ('libreoffice', 'ollama', 'tesseract', 'chrome-for-testing'):
            self.assertEqual(packages[name].source, PackageSource.CORE)
            self.assertIsNone(packages[name].module_dir)
            self.assertTrue((ROOT / 'core/deployment' / packages[name].installer).is_file())

    def test_valid_tool_model_and_python_group_references(self):
        self.manifest(tools=['ollama'], models=[{'provider': 'huggingface', 'repo': 'org/model', 'required': False}], python={'groups': ['analytics']})
        plan = resolve_plan(self.root)
        self.assertEqual(plan['tools'][0]['name'], 'ollama')
        self.assertEqual(plan['models'][0]['repo'], 'org/model')
        self.assertEqual(plan['python_groups'], ['analytics'])

    def test_invalid_versions_keys_types_and_duplicates_are_errors(self):
        for kwargs in ({'schema_version': 2}, {'schema_version': True}, {'typo': []}, {'tools': 'ollama'}, {'tools': ['ollama', 'ollama']}, {'tools': [{'name': 'ollama', 'required': 'false'}]}, {'python': {'groups': 'analytics'}}, {'models': [{'provider': 'other', 'name': 'x'}]}):
            with self.subTest(kwargs=kwargs):
                self.manifest(**kwargs)
                with self.assertRaises(RuntimeRequirementsError):
                    load_manifest(self.module)
        (self.module / 'runtime_requirements.yaml').write_text('schema_version: 1\ntools: []\ntools: []\n', encoding='utf-8')
        with self.assertRaises(RuntimeRequirementsError):
            load_manifest(self.module)

    def test_unknown_tool_and_unknown_python_group_are_errors_before_install(self):
        self.manifest(tools=['missing-tool'])
        with patch('runtime_requirements.plan.install_package') as install:
            with self.assertRaises(RuntimeRequirementsError):
                install_required_tools(self.root)
        install.assert_not_called()
        self.manifest(python={'groups': ['missing-group']})
        with self.assertRaises(RuntimeRequirementsError):
            required_python_groups(self.root)

    def test_disabled_and_unpopulated_modules_are_not_consumers(self):
        self.manifest(tools=['ollama'])
        placeholder = self.root / 'modules' / 'placeholder'
        placeholder.mkdir()
        (placeholder / 'runtime_requirements.yaml').write_text('invalid: true', encoding='utf-8')
        with patch.dict(os.environ, {'DISABLED_MODULES': 'consumer'}):
            self.assertEqual(discover_requirements(self.root), ())

    def test_legacy_core_references_work_and_full_redefinitions_fail(self):
        hook = self.module / 'packages.yaml'
        hook.write_text('packages:\n  ollama: {use: ollama}\n', encoding='utf-8')
        self.assertEqual(discover_packages(self.root)['ollama'].source, PackageSource.CORE)
        for value in ({'use': 'unknown'}, {'use': 'ollama', 'version': 'other'}, {'kind': 'custom', 'installer': 'other.py'}):
            hook.write_text(yaml.safe_dump({'packages': {'ollama': value}}), encoding='utf-8')
            with self.assertRaises(PackageRegistryError):
                discover_packages(self.root)

    def test_model_hooks_merge_equal_declarations_and_reject_conflicts(self):
        model = {'repo': 'org/model', 'required': False}
        self.manifest(models=[{'provider': 'huggingface', **model}])
        hook = self.module / 'huggingface_models.yaml'
        hook.write_text(yaml.safe_dump({'models': [model]}), encoding='utf-8')
        self.assertEqual(model_entries(self.module, 'huggingface'), [model])
        hook.write_text(yaml.safe_dump({'models': [{'repo': 'org/model', 'required': True}]}), encoding='utf-8')
        with self.assertRaises(RuntimeRequirementsError):
            model_entries(self.module, 'huggingface')

    def test_runtime_check_includes_hook_only_consumers_and_rejects_their_conflicts(self):
        hook = self.module / 'huggingface_models.yaml'
        hook.write_text('models:\n  - repo: org/model\n    required: true\n', encoding='utf-8')
        plan = resolve_plan(self.root)
        self.assertEqual(plan['modules'], ['consumer'])
        self.assertEqual(plan['models'], [{'provider': 'huggingface', 'module': 'consumer', 'repo': 'org/model', 'required': True}])
        hook.write_text('models:\n  - repo: org/model\n    required: true\n  - repo: org/model\n    required: false\n', encoding='utf-8')
        with self.assertRaises(RuntimeRequirementsError):
            resolve_plan(self.root)

    def test_huggingface_loader_accepts_new_manifest_without_old_hook(self):
        from huggingface.registry import load_resolved_models

        self.manifest(models=[{'provider': 'huggingface', 'repo': 'org/model', 'required': False}])
        models = load_resolved_models(self.root)
        self.assertEqual([(model.repo_id, model.required) for model in models], [('org/model', False)])

    def test_optional_tools_do_not_install_by_default_and_shared_tool_installs_once(self):
        self.manifest(tools=[{'name': 'ollama', 'required': False}])
        with patch('runtime_requirements.plan.install_package', return_value=0) as install:
            self.assertEqual(install_required_tools(self.root), 0)
            install.assert_not_called()
            self.assertEqual(install_required_tools(self.root, include_optional=True), 0)
            install.assert_called_once_with(self.root, 'ollama')
        other = self.root / 'modules' / 'other'
        (other / 'api').mkdir(parents=True)
        (other / 'runtime_requirements.yaml').write_text('schema_version: 1\ntools: [ollama]\n', encoding='utf-8')
        with patch('runtime_requirements.plan.install_package', return_value=0) as install:
            self.assertEqual(install_required_tools(self.root), 0)
            install.assert_called_once_with(self.root, 'ollama')

    def test_required_tool_failure_stops_the_runtime_phase(self):
        self.manifest(tools=['ollama', 'tesseract'])
        with patch('runtime_requirements.plan.install_package', return_value=17) as install:
            self.assertEqual(install_required_tools(self.root), 17)
            self.assertEqual(install.call_count, 1)

    def test_setup_places_tools_after_python_and_before_model_downloads(self):
        names = [step.name for step in RECIPE_REGISTRY['setup-full'].steps]
        self.assertLess(names.index('python_and_npm'), names.index('runtime_requirements'))
        self.assertLess(names.index('runtime_requirements'), names.index('pull_huggingface_models'))
        self.assertLess(names.index('runtime_requirements'), names.index('module_setup_tasks'))

    def test_runtime_phase_requires_venv_and_delegates_docker(self):
        ctx = DeploymentContext.create(self.root, runtime='host', raw_env={})
        with patch('lifecycle.host.ops.venv_exists', return_value=False):
            self.assertFalse(RuntimeRequirementsStep().run(ctx).ok)
        ctx.runtime = 'docker'
        with patch('lifecycle.docker.ops.run_api_oneoff', return_value=7) as run:
            self.assertEqual(RuntimeRequirementsStep().run(ctx).exit_code, 7)
        self.assertIn('packages/cli.py --root /app install-required', run.call_args.args[0])

    def test_repeat_actual_runtime_setup_does_not_download_or_replace_ready_tool(self):
        archive = self.root / 'payload.zip'
        payload = os.urandom(4096)
        with zipfile.ZipFile(archive, 'w') as zip_file:
            zip_file.writestr('bin/demo', payload)
        (self.module / 'packages.yaml').write_text(yaml.safe_dump({'packages': {'demo': {
            'kind': 'archive', 'dest': 'demo', 'platforms': {
                key: {'url': archive.as_uri(), 'archive': 'zip', 'marker': 'bin/demo'}
                for key in ('windows', 'linux')
            },
        }}}), encoding='utf-8')
        self.manifest(tools=['demo'])
        ctx = DeploymentContext.create(self.root, runtime='host', raw_env={'DISABLED_MODULES': ''})
        step = RuntimeRequirementsStep()
        with patch('lifecycle.host.ops.venv_exists', return_value=True), patch('lifecycle.host.ops.venv_python_exe', return_value=Path(sys.executable)):
            self.assertEqual(DeploymentPipeline([step]).run(ctx), 0)
            marker = self.root / 'virtual_env/packages/demo/bin/demo'
            original = marker.stat().st_mtime_ns
            archive.unlink()
            for cached in (self.root / 'virtual_env/cache/downloads').iterdir():
                cached.unlink()
            self.assertEqual(DeploymentPipeline([step]).run(ctx), 0)
        self.assertEqual(marker.read_bytes(), payload)
        self.assertEqual(marker.stat().st_mtime_ns, original)

    def test_bootstrap_recipe_import_does_not_require_yaml(self):
        code = "import sys;sys.path.insert(0,sys.argv[1]);sys.modules['yaml']=None;from lifecycle.recipes import RECIPE_REGISTRY;assert 'setup-full' in RECIPE_REGISTRY"
        result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'core/deployment')], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_python_install_selects_manifest_groups_through_existing_poetry(self):
        sys.path.insert(0, str(ROOT / 'core/api'))
        from commands.install import _runtime_extra_groups

        self.manifest(python={'groups': ['analytics']})
        self.assertEqual(_runtime_extra_groups(self.root), frozenset({'analytics'}))

    def test_python_install_without_yaml_defers_manifest_until_core_install(self):
        code = (
            "import sys;from pathlib import Path;"
            "sys.path[:0]=sys.argv[1:3];sys.modules['yaml']=None;"
            "from commands.install import _runtime_extra_groups;"
            "assert _runtime_extra_groups(Path(sys.argv[3]))==frozenset()"
        )
        result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'core/api'), str(ROOT / 'core/deployment'), str(self.root)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_repeat_python_setup_with_manifest_group_skips_poetry_install(self):
        sys.path.insert(0, str(ROOT / 'core/api'))
        from commands.install import InstallCommand

        self.manifest(python={'groups': ['analytics']})
        command = InstallCommand()
        with patch.object(command, '_find_project_root', return_value=self.root), patch.object(command, '_scan_module_configs', return_value=[]), patch.object(command, '_python_deps_stamp_matches', return_value=True), patch.object(command, '_core_lock_satisfied', return_value=True), patch.object(command, '_write_python_deps_stamp') as stamp, patch.object(command, '_install_core') as install:
            self.assertEqual(command.run(), 0)
            self.assertEqual(command.run(), 0)
        install.assert_not_called()
        self.assertEqual(stamp.call_count, 2)

    def test_download_policy_and_paths_fail_validation_before_install(self):
        hook = self.module / 'packages.yaml'
        for invalid in ({'marker_windows': '../escape'}, {'extra_dirs': ['..']}, {'download': {'sha256': {'asset.zip': 'wrong'}}}, {'download': {'mirrors': ['https://example.test/{unknown}']}}):
            hook.write_text(yaml.safe_dump({'packages': {'demo': {'kind': 'custom', 'installer': 'deployment/install.py', **invalid}}}), encoding='utf-8')
            with self.subTest(invalid=invalid), self.assertRaises(PackageRegistryError):
                discover_packages(self.root)

    def test_model_provider_with_wrong_type_is_a_controlled_manifest_error(self):
        for provider in (['huggingface'], {'kind': 'ollama'}):
            self.manifest(models=[{'provider': provider, 'name': 'demo'}])
            with self.subTest(provider=provider), self.assertRaises(RuntimeRequirementsError):
                load_manifest(self.module)

    def test_duplicate_package_definitions_are_rejected(self):
        (self.module / 'packages.yaml').write_text('packages:\n  demo: {kind: custom, installer: first.py}\n  demo: {kind: custom, installer: second.py}\n', encoding='utf-8')
        with self.assertRaises(PackageRegistryError):
            discover_packages(self.root)

    def test_manifest_with_invalid_utf8_is_a_controlled_error(self):
        (self.module / 'runtime_requirements.yaml').write_bytes(b'schema_version: 1\nmodule: \xff\n')
        with self.assertRaises(RuntimeRequirementsError):
            load_manifest(self.module)

    def test_legacy_model_hook_supports_yaml_merge_keys(self):
        (self.module / 'huggingface_models.yaml').write_text('models:\n  - &base\n    repo: org/base\n    required: false\n  - <<: *base\n    repo: org/other\n', encoding='utf-8')
        self.assertEqual(model_entries(self.module, 'huggingface'), [{'repo': 'org/base', 'required': False}, {'repo': 'org/other', 'required': False}])
        (self.module / 'huggingface_models.yaml').write_text('first: &first {required: false, repo: org/first}\nsecond: &second {<<: *first, repo: org/second}\nmodels:\n  - {<<: *second, repo: org/third}\n  - *second\n', encoding='utf-8')
        self.assertEqual(model_entries(self.module, 'huggingface'), [{'repo': 'org/third', 'required': False}, {'repo': 'org/second', 'required': False}])

    def test_conflicting_repo_and_name_aliases_are_rejected(self):
        self.manifest(models=[{'provider': 'huggingface', 'repo': 'org/first', 'name': 'org/second'}])
        with self.assertRaises(RuntimeRequirementsError):
            load_manifest(self.module)

    def test_huggingface_model_respects_process_environment(self):
        from huggingface.registry import load_resolved_models

        self.manifest(models=[{'provider': 'huggingface', 'env': 'ERGO_TEST_RUNTIME_MODEL', 'default': 'org/default'}])
        (self.module / '.env').write_text('ERGO_TEST_RUNTIME_MODEL=org/file\n', encoding='utf-8')
        with patch.dict(os.environ, {'ERGO_TEST_RUNTIME_MODEL': 'org/process'}):
            self.assertEqual(load_resolved_models(self.root)[0].repo_id, 'org/process')

    def test_unresolved_required_huggingface_model_fails(self):
        from huggingface.registry import load_resolved_models

        self.manifest(models=[{'provider': 'huggingface', 'env': 'ERGO_TEST_RUNTIME_UNRESOLVED'}])
        with patch.dict(os.environ, {'ERGO_TEST_RUNTIME_UNRESOLVED': ''}), self.assertRaises(RuntimeRequirementsError):
            load_resolved_models(self.root)

    def test_unresolved_optional_huggingface_model_is_skipped(self):
        from huggingface.registry import load_resolved_models

        self.manifest(models=[{'provider': 'huggingface', 'env': 'ERGO_TEST_RUNTIME_UNRESOLVED', 'required': False}])
        with patch.dict(os.environ, {'ERGO_TEST_RUNTIME_UNRESOLVED': ''}):
            self.assertEqual(load_resolved_models(self.root), ())

    def test_equal_model_aliases_are_normalized(self):
        self.manifest(models=[{'provider': 'huggingface', 'repo': ' org/model ', 'name': 'org/model'}])
        self.assertEqual(model_entries(self.module, 'huggingface'), [{'repo': 'org/model', 'required': True}])

    def test_legacy_package_merge_keys_are_preserved(self):
        (self.module / 'packages.yaml').write_text('defaults: &base {kind: custom, installer: install.py}\npackages:\n  demo: {<<: *base, dest: demo}\n', encoding='utf-8')
        self.assertEqual(discover_packages(self.root)['demo'].installer, 'install.py')

    def test_minimum_file_sizes_are_strictly_validated(self):
        for sizes in ([1], {'../outside': 10}, {'binary': True}, {'binary': 0}, {'binary': '1024'}):
            (self.module / 'packages.yaml').write_text(yaml.safe_dump({'packages': {'demo': {'kind': 'custom', 'installer': 'install.py', 'minimum_sizes': sizes}}}), encoding='utf-8')
            with self.subTest(sizes=sizes), self.assertRaises(PackageRegistryError):
                discover_packages(self.root)

    def test_invalid_python_group_configuration_is_a_controlled_error(self):
        self.manifest(python={'groups': ['analytics']})
        for content in (b'tool = 1\n', b'[tool.poetry]\ngroup = "invalid"\n', b'\xff'):
            (self.root / 'pyproject.toml').write_bytes(content)
            with self.subTest(content=content), self.assertRaises(RuntimeRequirementsError):
                required_python_groups(self.root)


if __name__ == '__main__':
    unittest.main()
