from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

import _bootstrap  # noqa: F401

from system_test.docker_env import DockerEnvironment  # noqa: E402
from system_test.os_services_env import OsServicesEnvironment  # noqa: E402
from system_test.worktree_env import HostWorktreeEnvironment  # noqa: E402


class SystemEnvironmentCleanupTests(unittest.TestCase):
    environments = (HostWorktreeEnvironment, DockerEnvironment, OsServicesEnvironment)

    def test_host_download_cache_is_owned_by_the_test_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            source = workspace / 'virtual_env/cache/downloads'
            source.mkdir(parents=True)
            (source / 'runtime.zip').write_bytes(b'archive')
            env = HostWorktreeEnvironment(workspace, workspace / 'run', 'ergo_st_cache')
            env.tree_root.mkdir(parents=True)
            env._link_download_cache()
            target = env.tree_root / 'virtual_env/cache/downloads'
            self.assertNotEqual(source.resolve(), target.resolve())
            (target / 'runtime.zip').unlink()
            self.assertEqual((source / 'runtime.zip').read_bytes(), b'archive')

    def test_host_database_config_uses_the_loader_wrapper_and_private_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            env = HostWorktreeEnvironment(workspace, workspace / 'run', 'ergo_st_database')
            env.tree_root.mkdir(parents=True)
            with patch('system_test.worktree_env.pick_scenario_ports', return_value={'api': 18000, 'client': 18001}):
                env._write_throwaway_config()
            document = yaml.safe_load((env.tree_root / 'databases.yaml').read_text(encoding='utf-8'))
            database = document['databases']['default']
            self.assertEqual(database['engine'], 'sqlite')
            self.assertEqual(Path(database['name']), env.run_dir / 'scenario.sqlite3')

    def test_teardown_before_provision_does_not_run_workspace_commands(self) -> None:
        self.check_unconfigured_tree(create_tree=False)

    def test_teardown_after_partial_copy_does_not_run_workspace_commands(self) -> None:
        self.check_unconfigured_tree(create_tree=True)

    def check_unconfigured_tree(self, *, create_tree: bool) -> None:
        for kind in self.environments:
            with self.subTest(kind=kind.kind), tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp)
                env = kind(workspace, workspace / 'run', 'ergo_st_cleanup')
                if create_tree:
                    env.tree_root.mkdir(parents=True)
                env.run_ergoms = Mock(return_value=subprocess.CompletedProcess([], 0))
                env._force_remove_prefix_containers = Mock()
                env.teardown()
                env.run_ergoms.assert_not_called()
                env._force_remove_prefix_containers.assert_not_called()

    def test_configured_cleanup_runs_only_inside_test_tree(self) -> None:
        for kind in self.environments:
            with self.subTest(kind=kind.kind), tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp)
                env = kind(workspace, workspace / 'run', 'ergo_st_cleanup')
                env.tree_root.mkdir(parents=True)
                ports = {'api': 18000, 'client': 18001}
                with patch('system_test.worktree_env.pick_scenario_ports', return_value=ports), \
                        patch('system_test.docker_env.pick_scenario_ports', return_value=ports):
                    env._write_throwaway_config()
                env._force_remove_prefix_containers = Mock()
                with patch('system_test.environment.subprocess.run',
                           return_value=subprocess.CompletedProcess([], 0)) as run:
                    env.teardown()
                self.assertGreater(run.call_count, 0)
                for call in run.call_args_list:
                    self.assertEqual(call.kwargs['cwd'], str(env.tree_root))
                    self.assertEqual(call.kwargs['env']['ERGO_SERVICE_PREFIX'], env.prefix)


if __name__ == '__main__':
    unittest.main()
