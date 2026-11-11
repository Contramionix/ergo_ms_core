"""
Запуск Vite dev-сервера для VS Code / ergoms start-client-dev.

При NGINX_ENABLED=false: ждёт API ready, затем npm run dev.
Если CLIENT_PORT уже слушается, второй Vite не запускается.
При NGINX_ENABLED=true: выход без сообщений (клиент отдаётся через nginx).
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
_DEPLOYMENT_DIR = SCRIPTS_DIR.parent
if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cli_locale import t  # noqa: E402
from console_tags import format_console  # noqa: E402
from deployment_env import is_nginx_enabled, read_env  # noqa: E402
from lifecycle.host_process_guard import refuse_unwanted_core_service  # noqa: E402
from lifecycle.host_profile import SERVICE_CLIENT  # noqa: E402
from start_client_vite import run_vite_dev  # noqa: E402
from wait_api_ready import wait_for_api_ready  # noqa: E402

_PROJECT_ROOT = _DEPLOYMENT_DIR.parent.parent


def _client_listen_target() -> tuple[str, int]:
    host = read_env('CLIENT_HOST', 'localhost').strip() or 'localhost'
    raw_port = read_env('CLIENT_PORT', '8001').strip() or '8001'
    try:
        port = int(raw_port)
    except ValueError:
        port = 8001
    return host, port


def _client_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def main() -> int:
    if is_nginx_enabled():
        return 0
    refused = refuse_unwanted_core_service(
        SERVICE_CLIENT,
        message_key='host_refuses_core_client',
        project_root=_PROJECT_ROOT,
    )
    if refused:
        return refused
    host, port = _client_listen_target()
    if _client_port_open(port):
        url = f'http://{host}:{port}/'
        print(format_console('info', t('client_dev_already_running', port=port, url=url)))
        return 0
    wait_for_api_ready()
    return run_vite_dev()


if __name__ == '__main__':
    raise SystemExit(main())
