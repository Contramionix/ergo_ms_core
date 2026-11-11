"""Bootstrap sys.path for deployment unit tests (stdlib unittest)."""

from __future__ import annotations

import sys
from pathlib import Path

DEPLOYMENT_DIR = Path(__file__).resolve().parents[1]
DOCKER_DIR = DEPLOYMENT_DIR / 'docker'
NGINX_DIR = DEPLOYMENT_DIR / 'nginx'
LIFECYCLE_DIR = DEPLOYMENT_DIR / 'lifecycle'
SCRIPTS_DIR = DEPLOYMENT_DIR / 'scripts'

# Приоритет deployment/: scripts/loadtest.py не должен заслонять пакет loadtest/.
for path in reversed((DEPLOYMENT_DIR, DOCKER_DIR, NGINX_DIR, LIFECYCLE_DIR, SCRIPTS_DIR)):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
