"""
Пакеты с полем swarm_worker ставятся в том воркера.

Имена модулей сюда не пишутся: реестр сам находит packages.yaml.
Повторный запуск пропускает пакет, у которого маркер уже лежит в томе.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
_DEPLOYMENT_DIR = SCRIPTS_DIR.parent
if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))

from packages.installer import install_package  # noqa: E402
from packages.registry import discover_packages  # noqa: E402


def _root() -> Path:
    mounted = Path('/app')
    if (mounted / 'core' / 'deployment').is_dir():
        return mounted
    return _DEPLOYMENT_DIR.parent.parent


def main() -> int:
    root = _root()
    code = 0
    for spec in discover_packages(root).values():
        if not spec.swarm_worker:
            continue
        result = install_package(root, spec.name)
        if result != 0:
            code = result
    return code


if __name__ == '__main__':
    raise SystemExit(main())
