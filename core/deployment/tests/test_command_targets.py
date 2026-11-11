from __future__ import annotations

import re
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from command_targets import collect_command_problems, help_command_names  # noqa: E402
from lifecycle.recipes import RECIPE_REGISTRY  # noqa: E402

_ROOT = Path(__file__).resolve().parents[3]
_HELP = _ROOT / 'core' / 'deployment' / 'help.manifest.yaml'


class CommandTargetTests(unittest.TestCase):
    def test_help_and_conf_targets_exist(self) -> None:
        problems = collect_command_problems(_ROOT, recipes=set(RECIPE_REGISTRY))
        self.assertEqual(problems, [], msg='\n'.join(problems))

    def test_reinstall_summary_matches_install_all(self) -> None:
        text = _HELP.read_text(encoding='utf-8')
        names = help_command_names(text)
        self.assertIn('reinstall', names)
        match = re.search(
            r'- name: reinstall\n    summary: (.+)',
            text,
        )
        self.assertIsNotNone(match)
        summary = match.group(1)
        self.assertIn('install:all', summary)
        self.assertNotIn('npm ci', summary)


if __name__ == '__main__':
    unittest.main()
