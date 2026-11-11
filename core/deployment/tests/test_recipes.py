from __future__ import annotations

import re
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from lifecycle.recipes import RECIPE_REGISTRY  # noqa: E402


class RecipeRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.commands_conf = Path(__file__).resolve().parents[1] / 'commands.conf'
        cls.help_manifest = Path(__file__).resolve().parents[1] / 'help.manifest.yaml'

    def test_key_lifecycle_recipes_registered(self) -> None:
        for name in (
            'setup-full',
            'install-deps',
            'docker-init',
            'docker-up',
            'dev-api',
            'nginx-install',
            'service-install-all',
        ):
            self.assertIn(name, RECIPE_REGISTRY, msg=f'missing recipe {name}')

    def test_aliases_point_to_existing_recipes(self) -> None:
        for alias, target in (
            ('dev', 'dev-api'),
            ('install-nginx', 'nginx-install'),
            ('install-services', 'service-install-all'),
            ('install-python', 'install-python-runtime'),
        ):
            self.assertIn(alias, RECIPE_REGISTRY)
            self.assertIs(RECIPE_REGISTRY[alias], RECIPE_REGISTRY[target])

    def test_commands_conf_runner_recipes_exist(self) -> None:
        text = self.commands_conf.read_text(encoding='utf-8')
        recipe_names = set(re.findall(r'runner\.py ([a-z0-9-]+)', text))
        missing = sorted(name for name in recipe_names if name not in RECIPE_REGISTRY)
        self.assertEqual(missing, [], msg=f'commands.conf recipes missing from registry: {missing}')

    def test_help_manifest_docker_commands_have_recipes(self) -> None:
        text = self.help_manifest.read_text(encoding='utf-8')
        for name in ('docker-init', 'docker-up', 'docker-down', 'docker-migrate'):
            self.assertIn(f'name: {name}', text)
            self.assertIn(name, RECIPE_REGISTRY)

    def test_deploy_recipes_snapshot_before_migrate(self) -> None:
        all_names = [step.name for step in RECIPE_REGISTRY['deploy-all'].steps]
        self.assertLess(all_names.index('git_submodule_update'), all_names.index('record_deploy_revision'))
        self.assertLess(all_names.index('backup_database'), all_names.index('migrate'))
        api_names = [step.name for step in RECIPE_REGISTRY['deploy-api'].steps]
        self.assertLess(api_names.index('backup_database'), api_names.index('migrate'))
        api_revision = next(
            step for step in RECIPE_REGISTRY['deploy-api'].steps
            if step.name == 'record_deploy_revision'
        )
        all_revision = next(
            step for step in RECIPE_REGISTRY['deploy-all'].steps
            if step.name == 'record_deploy_revision'
        )
        self.assertEqual(api_revision.paths, ('core/api', 'core/media_api'))
        self.assertEqual(all_revision.paths, ('core/api', 'core/client', 'core/media_api'))
        self.assertNotIn('backup_database', [step.name for step in RECIPE_REGISTRY['deploy-client'].steps])


if __name__ == '__main__':
    unittest.main()
