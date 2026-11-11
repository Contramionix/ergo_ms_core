"""Include the API installer regressions in the standard deployment unit suite."""
from pathlib import Path
import unittest


def load_tests(loader, tests, pattern):
    directory = Path(__file__).resolve().parents[3] / 'core/api/tests'
    if not (directory / 'test_install_dependency_closure.py').is_file():
        def unavailable():
            raise unittest.SkipTest('API installer regression tests are absent in this checkout')
        tests.addTest(unittest.FunctionTestCase(unavailable))
    else:
        # A separate loader preserves the caller's discovery root.
        tests.addTests(unittest.TestLoader().discover(str(directory), pattern='test_install_dependency_closure.py'))
    return tests
