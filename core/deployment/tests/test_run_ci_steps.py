"""Имена шагов ergoms ci не запускают сами проверки."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import _bootstrap  # noqa: F401

import run_ci  # noqa: E402
from cli_locale import t  # noqa: E402
from run_ci import (  # noqa: E402
    FAST_STEP_LABELS,
    client_report_lines,
    client_test_files,
    keep_rules_line,
    lint_findings,
    nightly_step_labels,
    unit_success_lines,
)


class RunCiStepLabelTests(unittest.TestCase):
    def test_fast_labels_are_unique(self) -> None:
        self.assertEqual(
            FAST_STEP_LABELS,
            (
                'poetry.lock',
                'package-lock.json',
                'core-rules-check',
                'system-test unit',
                'lint:check',
                'client-tests',
            ),
        )
        self.assertEqual(len(FAST_STEP_LABELS), len(set(FAST_STEP_LABELS)))

    def test_nightly_scenario_labels_include_spec(self) -> None:
        labels = nightly_step_labels()
        self.assertEqual(
            labels,
            (
                'system-test scenarios host_sqlite_direct',
                'system-test scenarios docker_direct',
                'system-test security',
                'system-test browser',
            ),
        )
        scenarios = [label for label in labels if 'scenarios' in label]
        self.assertEqual(len(scenarios), 2)
        self.assertIn('host_sqlite_direct', scenarios[0])
        self.assertIn('docker_direct', scenarios[1])

    def test_disabled_module_client_tests_are_left_out(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as raw:
            root = Path(raw)
            kept = root / 'modules' / 'kept_mod' / 'client' / 'tests'
            skipped = root / 'modules' / 'paused_mod' / 'client' / 'tests'
            kept.mkdir(parents=True)
            skipped.mkdir(parents=True)
            (kept / 'alive.test.mjs').write_text('export {}\n', encoding='utf-8')
            (skipped / 'paused.test.mjs').write_text('export {}\n', encoding='utf-8')
            files = client_test_files(root, disabled=frozenset({'paused_mod'}))
        self.assertEqual([path.name for path in files], ['alive.test.mjs'])

    def test_lint_warnings_are_counts_by_rule(self) -> None:
        root = Path(r'Z:/ergo_ms')
        vue = root / 'modules' / 'crm' / 'client' / 'A.vue'
        payload = [
            {
                'filePath': str(vue),
                'messages': [
                    {
                        'ruleId': 'vuejs-accessibility/label-has-for',
                        'severity': 1,
                        'line': 4,
                        'message': 'label',
                    },
                    {
                        'ruleId': 'vuejs-accessibility/label-has-for',
                        'severity': 1,
                        'line': 8,
                        'message': 'label',
                    },
                    {
                        'ruleId': 'no-useless-assignment',
                        'severity': 1,
                        'line': 1,
                        'message': 'assign',
                    },
                    {
                        'ruleId': 'no-unused-vars',
                        'severity': 2,
                        'line': 3,
                        'message': "'x' is defined but never used",
                    },
                ],
            }
        ]
        errors, warnings = lint_findings(payload, root)
        self.assertEqual(
            errors,
            [('modules/crm/client/A.vue', 3, 'no-unused-vars', "'x' is defined but never used")],
        )
        self.assertEqual(
            warnings,
            [
                ('vuejs-accessibility/label-has-for', 2),
                ('no-useless-assignment', 1),
            ],
        )
        self.assertNotIn('A.vue', warnings[0][0])

    def test_lint_report_must_be_a_list(self) -> None:
        with self.assertRaises(ValueError):
            lint_findings({'messages': []}, Path('.'))

    def test_rules_output_hides_django_startup(self) -> None:
        self.assertFalse(keep_rules_line('Выполняется Django команда: manage.py validate_module_isolation'))
        self.assertFalse(
            keep_rules_line(
                '[INFO] 2026-10-28 09:27:47 config.database database Загружено 4 конфигураций БД'
            )
        )
        self.assertFalse(
            keep_rules_line(
                '[WARNING] 2026-10-28 09:28:50 modules.example FERNET_KEY не задан'
            )
        )
        self.assertTrue(keep_rules_line('[OK] Все проверки ядра пройдены'))
        self.assertTrue(
            keep_rules_line(
                '[WARNING] modules/projects/client/js/useProjects.js:6: import из @/modules/organizations/'
            )
        )

    def test_module_report_does_not_fail_rules_bundle(self) -> None:
        from validate_core_rules import _bundle_payload, bundle_failed_flags

        payload = _bundle_payload(
            '\n'.join(
                [
                    '[INFO] 2026-10-28 09:27:47 config.database database Загружено',
                    '{"core": {"failed": false}, "modules": {"failed": true}, "bridge": {"failed": false}}',
                ]
            )
        )
        self.assertEqual(bundle_failed_flags(payload), (False, False))
        self.assertEqual(
            bundle_failed_flags(
                {'core': {'failed': True}, 'modules': {'failed': False}, 'bridge': {'failed': True}}
            ),
            (True, True),
        )

    def test_unit_success_keeps_only_the_tally(self) -> None:
        text = '\n'.join(
            [
                '[ERROR] Не удалось получить проверенный файл',
                'Ran 694 tests in 178.570s',
                '',
                'OK (skipped=4)',
            ]
        )
        self.assertEqual(
            unit_success_lines(text),
            ['Ran 694 tests in 178.570s', 'OK (skipped=4)'],
        )

    def test_lock_failure_does_not_start_heavy_steps(self) -> None:
        calls: list[str] = []

        def run_step(label, *_args, **_kwargs):
            calls.append(label)
            return 1 if label == 'poetry.lock' else 0

        def perform(*_args, **_kwargs):
            calls.append('heavy')
            raise AssertionError('heavy step started')

        with (
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
            patch.object(run_ci, '_node_binary', return_value=Path('node')),
            patch.object(run_ci, '_npm_binary', return_value='npm'),
            patch.object(run_ci, '_run', side_effect=run_step),
            patch.object(run_ci, '_perform', side_effect=perform),
        ):
            code = run_ci._fast_steps(Path('.'))
        self.assertEqual(code, 1)
        self.assertEqual(calls, ['poetry.lock'])

    def test_heavy_steps_run_together_and_lint_failure_wins(self) -> None:
        calls: list[str] = []

        def perform(_root, _node, _scripts, _py, label):
            calls.append(label)
            code = 1 if label == 'lint:check' else 0
            return label, code, [], 1

        with (
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
            patch.object(run_ci, '_node_binary', return_value=Path('node')),
            patch.object(run_ci, '_npm_binary', return_value='npm'),
            patch.object(run_ci, '_run', side_effect=lambda label, *_a, **_k: calls.append(label) or 0),
            patch.object(run_ci, '_perform', side_effect=perform),
        ):
            code = run_ci._fast_steps(Path('.'))
        self.assertEqual(code, 1)
        self.assertEqual(calls[:2], ['poetry.lock', 'package-lock.json'])
        self.assertCountEqual(calls[2:], list(run_ci.PARALLEL_STEP_LABELS))

    def test_client_success_is_a_tally_without_names_or_ansi(self) -> None:
        text = '\n'.join(
            [
                '\x1b[32m✔\x1b[39m keeps the widget',
                '✔ another case',
                'ℹ tests 2',
                'ℹ suites 0',
                'ℹ pass 2',
                'ℹ fail 0',
                'ℹ cancelled 0',
                'ℹ skipped 0',
                'ℹ todo 0',
                'ℹ duration_ms 12.5',
                '\x1b[8A',
            ]
        )
        lines = client_report_lines(text, 0)
        self.assertEqual(lines, [t('ci_client_tests_tally', tests=2, passed=2)])
        self.assertNotIn('\x1b', ''.join(lines))
        self.assertNotIn('keeps the widget', ''.join(lines))

    def test_client_success_mentions_skipped(self) -> None:
        text = '\n'.join(
            [
                '✔ one',
                'ℹ tests 2',
                'ℹ pass 1',
                'ℹ fail 0',
                'ℹ cancelled 0',
                'ℹ skipped 1',
                'ℹ todo 0',
            ]
        )
        self.assertEqual(
            client_report_lines(text, 0),
            [t('ci_client_tests_tally_skipped', tests=2, passed=1, skipped=1)],
        )

    def test_client_failure_keeps_failures_and_drops_passes(self) -> None:
        text = '\n'.join(
            [
                '✔ ok case',
                '\x1b[31m✖\x1b[39m broken case',
                '  AssertionError: nope',
                'ℹ tests 2',
                'ℹ pass 1',
                'ℹ fail 1',
                '\x1b[1A',
            ]
        )
        lines = client_report_lines(text, 1)
        self.assertEqual(
            lines,
            [
                '✖ broken case',
                'AssertionError: nope',
                'ℹ tests 2',
                'ℹ pass 1',
                'ℹ fail 1',
            ],
        )
        self.assertNotIn('\x1b', '\n'.join(lines))

    def test_client_todo_keeps_summary_without_pass_names(self) -> None:
        text = '\n'.join(
            [
                '✔ done',
                'ℹ tests 2',
                'ℹ pass 1',
                'ℹ fail 0',
                'ℹ cancelled 0',
                'ℹ skipped 0',
                'ℹ todo 1',
            ]
        )
        lines = client_report_lines(text, 0)
        self.assertTrue(any('todo 1' in line for line in lines))
        self.assertFalse(any(line.startswith('✔') for line in lines))

    def test_client_success_without_summary_drops_names(self) -> None:
        self.assertEqual(client_report_lines('✔ only a name\n', 0), [])

    def test_parallel_heading_has_no_fraction(self) -> None:
        with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
            run_ci._announce(
                'client-tests',
                index=6,
                total=6,
                code=0,
                lines=['Клиентские тесты: 43, прошли 43.'],
                seconds=12,
            )
        text = stdout.getvalue()
        self.assertEqual(stderr.getvalue(), '')
        self.assertIn('[INFO] client-tests', text)
        self.assertIn('[OK]', text)
        self.assertNotIn('6/6', text)
        self.assertNotIn('\x1b', text)

    def test_lock_heading_keeps_fraction(self) -> None:
        with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
            run_ci._announce(
                'poetry.lock',
                index=1,
                total=6,
                code=1,
                lines=['\x1b[8A'],
                seconds=3,
            )
        text = stdout.getvalue()
        self.assertEqual(stderr.getvalue(), '')
        self.assertIn('[1/6] poetry.lock', text)
        self.assertIn('[ERROR]', text)
        self.assertNotIn('\x1b', text)


if __name__ == '__main__':
    unittest.main()
