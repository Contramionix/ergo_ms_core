"""Показ ergoms help: короткая команда в колонке, длинный вызов на своей строке."""

from __future__ import annotations

import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from ergoms_help import (  # noqa: E402
    _WORDMARK,
    render_core,
    render_overview,
    render_section,
    resolve_help_subargs,
)

_ROOT = Path(__file__).resolve().parents[3]
_COLUMN = 45
_REMOVED = (
    'deployment-test',
    'test_system',
    'test-system',
    'start-all-services',
    'stop-all-services',
    'restart-all-services',
    'status-all-services',
)
_SYSTEM_TEST_INVOKE = (
    'ergoms system-test [--suite unit|install|commands|scenarios|security|performance|browser|os-services|all] '
    '[--launch docker|host|os-services] [--spec host_sqlite_direct] [--strict]'
)


class ErgomsHelpLayoutTests(unittest.TestCase):
    def test_help_layout_across_languages(self) -> None:
        for language in ('ru', 'en', 'fr'):
            with self.subTest(language=language):
                lines = render_core(_ROOT, 'windows', language, width=200).splitlines()
                text = '\n'.join(lines)
                for name in _REMOVED:
                    self.assertNotIn(name, text)

                short = next(line for line in lines if 'ergoms start-api-service' in line)
                self.assertTrue(short.startswith('  ergoms start-api-service'))
                self.assertEqual(short[_COLUMN - 1], ' ')
                self.assertNotEqual(short[_COLUMN], ' ')

                index = next(i for i, line in enumerate(lines) if line == f'  {_SYSTEM_TEST_INVOKE}')
                summary = lines[index + 1]
                self.assertTrue(summary.startswith(' ' * _COLUMN))
                self.assertNotEqual(summary[_COLUMN], ' ')

    def test_overview_lists_sections_without_commands(self) -> None:
        headings = {'ru': 'Работа', 'en': 'Work', 'fr': 'Travail'}
        others = {'ru': 'Прочее', 'en': 'Other', 'fr': 'Divers'}
        dev_about = {
            'ru': 'локальный API, клиент и фоновые задачи',
            'en': 'local API, client, and background jobs',
            'fr': 'API, client et tâches de fond en local',
        }
        for language, heading in headings.items():
            with self.subTest(language=language):
                text = render_overview(_ROOT, 'windows', language, width=80)
                self.assertTrue(text.startswith('\n' + _WORDMARK[0]))
                self.assertIn('░███████', text)
                self.assertIn(dev_about[language], text)
                self.assertTrue(all(len(line) <= 80 for line in text.splitlines()))
                self.assertIn(f'\n{heading}\n', text)
                self.assertLess(text.index(f'\n{heading}\n'), text.index('\n  dev '))
                self.assertLess(text.index('\n  nginx-service '), text.index(f'\n{others[language]}\n'))
                self.assertNotIn('builtin_services', text)
                self.assertNotIn('service_aliases', text)
                self.assertIn('ergoms help all', text)
                self.assertNotIn('ergoms start-api-service', text)
                dev_line = next(line for line in text.splitlines() if line.startswith('  dev '))
                self.assertRegex(dev_line, r'^  dev {13}— ')

                medium = render_overview(_ROOT, 'windows', language, width=50)
                self.assertNotIn(_WORDMARK[0], medium)
                self.assertIn(dev_about[language], medium)

                narrow = render_overview(_ROOT, 'windows', language, width=20)
                self.assertNotIn(_WORDMARK[0], narrow)
                self.assertIn(f'\n{heading}\n', narrow)

        full = render_core(_ROOT, 'windows', 'ru')
        section = render_section(_ROOT, 'windows', 'dev', 'ru')
        self.assertNotIn(_WORDMARK[0], full)
        self.assertNotIn(_WORDMARK[0], section)
        self.assertTrue(section.startswith('Локальная разработка\n'))
        self.assertNotIn(dev_about['ru'], section)
        linux = render_overview(_ROOT, 'linux', 'ru', width=80)
        self.assertIn('служба redis в systemd', linux)
        self.assertIn('сертификат TLS для Linux', linux)
        self.assertNotIn('служба nginx в Windows', linux)

    def test_dev_section_wraps_long_summary(self) -> None:
        summary = (
            'Логи БД, Redis, Meilisearch и Jupyter (если включены), API, клиент, '
            'Media API, worker и beat (без служб ОС)'
        )
        lines = render_section(_ROOT, 'windows', 'dev', 'ru', width=80).splitlines()
        self.assertTrue(all(len(line) <= 80 for line in lines))
        self.assertTrue(all(not line or line.startswith('  ') or line == lines[0] for line in lines))
        index = next(i for i, line in enumerate(lines) if line.startswith('  ergoms start-all '))
        self.assertTrue(lines[index + 1].startswith(' ' * _COLUMN))
        self.assertNotEqual(lines[index + 1][_COLUMN], ' ')
        parts = [lines[index][_COLUMN:].strip()]
        cursor = index + 1
        while cursor < len(lines) and lines[cursor].startswith(' ' * _COLUMN):
            parts.append(lines[cursor][_COLUMN:].strip())
            cursor += 1
        self.assertEqual(' '.join(parts), summary)

    def test_section_help_shows_only_that_section(self) -> None:
        services = render_section(_ROOT, 'windows', 'services', 'ru')
        self.assertEqual(services, render_section(_ROOT, 'windows', 'builtin_services', 'ru'))
        self.assertIn('ergoms start ', services)
        self.assertNotIn('ergoms system-test', services)
        self.assertNotIn('ergoms docker-up', services)

        development = render_section(_ROOT, 'windows', 'dev', 'ru')
        self.assertEqual(development, render_section(_ROOT, 'windows', 'development', 'ru'))
        self.assertIn('ergoms start-all', development)

        separate = render_section(_ROOT, 'windows', 'os-services', 'ru')
        self.assertIn('ergoms start-api-service', separate)
        self.assertNotIn('ergoms system-test', separate)

    def test_unknown_section_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            render_section(_ROOT, 'windows', 'no-such-section', 'ru')

    def test_help_args_resolve_overview_all_and_section(self) -> None:
        self.assertEqual(resolve_help_subargs([]), ('overview', None))
        self.assertEqual(resolve_help_subargs(['all']), ('all', None))
        self.assertEqual(resolve_help_subargs(['development']), ('section', 'development'))
        self.assertEqual(resolve_help_subargs(['modules']), ('modules', None))


if __name__ == '__main__':
    unittest.main()
