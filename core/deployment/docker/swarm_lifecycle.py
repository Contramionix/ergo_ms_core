"""Точка входа ergoms start/stop: стек воркеров и наблюдатель плана."""

from __future__ import annotations

import sys
from pathlib import Path

DOCKER_DIR = Path(__file__).resolve().parent
DEPLOYMENT_DIR = DOCKER_DIR.parent
if str(DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOYMENT_DIR))
if str(DOCKER_DIR) not in sys.path:
    sys.path.insert(0, str(DOCKER_DIR))

import swarm_runtime  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    action = args[0] if args else ''
    if action == 'start':
        return swarm_runtime.sync_on_start()
    if action == 'stop':
        return swarm_runtime.sync_on_stop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
