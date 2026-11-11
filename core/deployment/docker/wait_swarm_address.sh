#!/bin/sh
# Ждёт локальный адрес менеджера Swarm, чтобы dockerd занял порт при старте.
# Кластер выключен или адреса нет — выходим сразу, Docker стартует как обычно.
set -eu
here=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
root=$(CDPATH= cd -- "$here/../../.." && pwd)
py="$root/virtual_env/python/bin/python"
if [ ! -x "$py" ]; then
  exit 0
fi
info=$("$py" -c '
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from celery_balance.settings import load_settings
from env_file_loader import load_project_env
root = Path(sys.argv[2])
env = load_project_env(root)
settings = load_settings(root)
host = str(env.get("DOCKER_SWARM_MANAGER_HOST") or "").strip()
if not host:
    registry = str(env.get("DOCKER_SWARM_REGISTRY") or "").strip()
    host = registry.rsplit(":", 1)[0] if ":" in registry else registry
sys.stdout.write(("1" if settings.cluster_enabled else "0") + "\n" + host + "\n")
' "$root/core/deployment" "$root") || exit 0
cluster=$(printf '%s\n' "$info" | sed -n '1p')
host=$(printf '%s\n' "$info" | sed -n '2p')
if [ "$cluster" != "1" ] || [ -z "$host" ]; then
  exit 0
fi
i=0
while [ "$i" -lt 30 ]; do
  if ip -4 -o addr show 2>/dev/null | grep -F "inet ${host}/" >/dev/null 2>&1; then
    exit 0
  fi
  i=$((i + 1))
  sleep 1
done
exit 0
