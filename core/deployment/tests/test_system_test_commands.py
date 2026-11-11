from __future__ import annotations

import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import _bootstrap  # noqa: F401

from system_test.cases.commands import CommandsSmokeCase  # noqa: E402


class DockerCommandsSmokeTests(unittest.TestCase):
    def environment(self, docker_ps_code: int = 0, docker_logs_code: int = 0):
        def run(command, *args, **kwargs):
            codes = {'status': 1, 'logs': 1, 'docker-ps': docker_ps_code, 'docker-logs': docker_logs_code}
            code = codes.get(command, 0)
            return subprocess.CompletedProcess([command, *args], code, stdout='', stderr='')

        return SimpleNamespace(kind='docker', prefix='ergo_st_smoke', run_ergoms=Mock(side_effect=run))

    def test_docker_commands_do_not_require_windows_service_administration(self) -> None:
        env = self.environment()
        result = CommandsSmokeCase().run(env)
        self.assertEqual(result.status, 'ok', result.detail)
        commands = [call.args[0] for call in env.run_ergoms.call_args_list]
        self.assertNotIn('status', commands)
        self.assertNotIn('logs', commands)
        self.assertEqual(commands.count('docker-ps'), 1)
        self.assertEqual(commands.count('docker-logs'), 1)

    def test_docker_status_failure_is_reported(self) -> None:
        result = CommandsSmokeCase().run(self.environment(docker_ps_code=2))
        self.assertEqual(result.status, 'fail')
        self.assertIn('docker-ps:2', result.detail)

    def test_docker_logs_failure_is_reported(self) -> None:
        result = CommandsSmokeCase().run(self.environment(docker_logs_code=2))
        self.assertEqual(result.status, 'fail')
        self.assertIn('docker-logs:2', result.detail)


if __name__ == '__main__':
    unittest.main()
