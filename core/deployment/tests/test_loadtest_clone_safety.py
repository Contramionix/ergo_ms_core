from unittest import TestCase
from unittest.mock import MagicMock, patch

import _bootstrap  # noqa: F401

from loadtest.isolated_db import DefaultDbConfig, refresh_clone


class LoadtestCloneSafetyTests(TestCase):
    def test_refresh_never_terminates_source_database_sessions(self):
        config = DefaultDbConfig('postgresql', 'source', 'owner', '', 'localhost', 5432)
        connection = MagicMock()
        with patch('loadtest.isolated_db._connect_admin') as connect, patch(
            'loadtest.isolated_db._terminate_db_backends',
        ) as terminate:
            connect.return_value.__enter__.return_value = connection
            self.assertEqual(refresh_clone(config), 'source_loadtest')
        terminate.assert_called_once_with(connection, 'source_loadtest')

    def test_source_cannot_be_used_as_the_clone(self):
        config = DefaultDbConfig('postgresql', 'source', 'owner', '', 'localhost', 5432)
        with patch('loadtest.isolated_db._connect_admin') as connect:
            with self.assertRaises(RuntimeError):
                refresh_clone(config, clone_name='source')
        connect.assert_not_called()
