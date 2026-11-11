"""Реестр образов и стек Swarm для воркеров Celery."""

from __future__ import annotations

import errno
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from cli_locale import t
from console_tags import format_console
from env_file_loader import load_project_env, parse_env_file
from project_layout import cache_dir, ensure_dir

from generate_swarm_stack import OUTPUT, ollama_bind, ollama_enabled, render_stack

STACK_NAME = 'ergo_workers'
REGISTRY_NAME = 'ergo-registry'
IMAGE_NAME = 'ergo-worker:local'


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _env(root: Path) -> dict[str, str]:
    return load_project_env(root)


def _registry(env: dict[str, str]) -> str:
    return str(env.get('DOCKER_SWARM_REGISTRY') or '').strip()


def _manager_host(env: dict[str, str], registry: str) -> str:
    host = str(env.get('DOCKER_SWARM_MANAGER_HOST') or '').strip()
    if host:
        return host
    if ':' in registry:
        return registry.rsplit(':', 1)[0]
    return registry


def _gpu_enabled(env: dict[str, str]) -> bool:
    raw = str(env.get('DOCKER_SWARM_GPU') or 'true').strip().lower()
    return raw not in {'0', 'false', 'no', 'off'}


def _docker() -> list[str] | None:
    """docker из PATH. Если сокет недоступен, а sudo без пароля есть — через него."""
    cached = getattr(_docker, '_argv', None)
    if cached is not None:
        return cached or None
    binary = shutil.which('docker')
    if not binary:
        _docker._argv = []  # type: ignore[attr-defined]
        return None
    direct = subprocess.run([binary, 'info'], capture_output=True, text=True, check=False)
    if direct.returncode == 0:
        argv = [binary]
    else:
        sudo = shutil.which('sudo')
        elevated = (
            subprocess.run(
                [sudo, '-n', binary, 'info'],
                capture_output=True,
                text=True,
                check=False,
            )
            if sudo
            else None
        )
        argv = [sudo, '-n', binary] if elevated is not None and elevated.returncode == 0 else [binary]
    _docker._argv = argv  # type: ignore[attr-defined]
    return argv


def _run(cmd: list[str]) -> int:
    result = subprocess.run(cmd, check=False)
    return int(result.returncode)


def _quote_env(value: str) -> str:
    text = str(value).replace('\r', '').replace('\n', '')
    escaped = text.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


_LOOPBACK_PROXY_KEYS = (
    'HTTP_PROXY',
    'HTTPS_PROXY',
    'ALL_PROXY',
    'http_proxy',
    'https_proxy',
    'all_proxy',
)


def _drop_loopback_proxies(env: dict[str, str]) -> None:
    """Прокси на 127.0.0.1 есть только на этой машине. На узле Chrome из-за него сразу падает."""
    for key in _LOOPBACK_PROXY_KEYS:
        value = str(env.get(key) or '')
        if '127.0.0.1' in value or 'localhost' in value:
            env.pop(key, None)


def _rewrite_local_hosts(node: object, manager_host: str) -> None:
    """127.0.0.1 в databases.yaml — эта машина. На узле это уже не она."""
    if not isinstance(node, dict):
        return
    host = str(node.get('host') or '').strip()
    if host in {'127.0.0.1', 'localhost'}:
        node['host'] = manager_host
    for value in node.values():
        if isinstance(value, dict):
            _rewrite_local_hosts(value, manager_host)


def prepare_worker_files(root: Path, manager_host: str) -> tuple[Path, Path]:
    """Копии .env и databases.yaml в кэше. Swarm раздаёт их воркерам как config."""
    import yaml

    folder = ensure_dir(cache_dir(root) / 'swarm-config')
    merged = load_project_env(root)
    _drop_loopback_proxies(merged)
    modules = root / 'modules'
    if modules.is_dir():
        for path in sorted(modules.glob('*/.env')):
            merged.update(parse_env_file(path))
    dotenv = folder / 'dotenv'
    lines = [f'{key}={_quote_env(value)}' for key, value in sorted(merged.items())]
    dotenv.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    databases_src = root / 'databases.yaml'
    databases = folder / 'databases.yaml'
    if databases_src.is_file():
        raw = databases_src.read_text(encoding='utf-8')
        try:
            parsed = yaml.safe_load(raw) or {}
        except Exception:  # noqa: BLE001
            parsed = {}
        if isinstance(parsed, dict):
            _rewrite_local_hosts(parsed, manager_host)
            databases.write_text(
                yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False),
                encoding='utf-8',
            )
        else:
            shutil.copyfile(databases_src, databases)
    else:
        databases.write_text('{}\n', encoding='utf-8')
    return dotenv, databases


def _postgres_port(databases: Path) -> str:
    """Порт из databases.yaml. Portable слушает не 5432, и ожидание на узле иначе не кончается."""
    import yaml

    try:
        parsed = yaml.safe_load(databases.read_text(encoding='utf-8')) or {}
    except (OSError, yaml.YAMLError):
        return '5432'
    section = parsed.get('databases') if isinstance(parsed, dict) else None
    default = section.get('default') if isinstance(section, dict) else None
    if not isinstance(default, dict):
        default = parsed.get('default') if isinstance(parsed, dict) else None
    if isinstance(default, dict) and default.get('port'):
        return str(default['port'])
    return '5432'


def _media_internal_key(root: Path) -> str:
    """Ключ internal API media. Пустой файл заполняется, иначе воркер узла не читает файлы."""
    path = root / 'env' / 'media.env'
    if not path.is_file():
        return ''
    from security.ensure_secret import (  # noqa: WPS433
        MEDIA_API_INTERNAL_KEY,
        _file_value,
        _upsert_env_key,
        generate_secret_hex,
        secret_value_is_empty,
    )

    current = _file_value(path, MEDIA_API_INTERNAL_KEY).strip().strip('"').strip("'")
    if not secret_value_is_empty(current):
        return current
    secret = generate_secret_hex()
    _upsert_env_key(path, MEDIA_API_INTERNAL_KEY, secret)
    return secret


def write_stack(root: Path) -> Path:
    env = _env(root)
    registry = _registry(env)
    if not registry:
        raise SystemExit(format_console('error', t('docker_swarm_registry_missing')))
    dotenv, databases = prepare_worker_files(root, _manager_host(env, registry))
    serve_on_node = ollama_enabled(env)
    bind = ollama_bind(env)
    if serve_on_node and not bind:
        raise SystemExit(format_console('error', t('docker_swarm_ollama_bind_missing')))
    content = render_stack(
        image=f'{registry}/{IMAGE_NAME}',
        manager_host=_manager_host(env, registry),
        databases_file=str(databases),
        env_file=str(dotenv),
        gpu=_gpu_enabled(env),
        media_url=str(env.get('DOCKER_SWARM_MEDIA_URL') or '').strip(),
        media_internal_key=(
            _media_internal_key(root)
            if str(env.get('DOCKER_SWARM_MEDIA_URL') or '').strip()
            else ''
        ),
        ollama_url=str(env.get('DOCKER_SWARM_OLLAMA_URL') or '').strip(),
        db_port=_postgres_port(databases),
        ollama_service=serve_on_node,
        ollama_bind=bind,
        ollama_image=f'{registry}/ollama:local' if serve_on_node else '',
    )
    OUTPUT.write_text(content, encoding='utf-8')
    print(format_console('ok', t('docker_swarm_stack_written', output=OUTPUT)))
    return OUTPUT


def cmd_registry() -> int:
    root = _root()
    env = _env(root)
    registry = _registry(env)
    if not registry:
        print(format_console('error', t('docker_swarm_registry_missing')), file=sys.stderr)
        return 1
    docker = _docker()
    if not docker:
        print(format_console('error', t('docker_not_found_short')), file=sys.stderr)
        return 1
    host = _manager_host(env, registry)
    port = registry.rsplit(':', 1)[-1] if ':' in registry else '5000'
    data = ensure_dir(cache_dir(root) / 'docker-registry')
    _run([*docker, 'rm', '-f', REGISTRY_NAME])
    code = _run([
        *docker, 'run', '-d',
        '--name', REGISTRY_NAME,
        '--restart', 'unless-stopped',
        '-p', f'{host}:{port}:5000',
        '-v', f'{data}:/var/lib/registry',
        'registry:2',
    ])
    if code != 0:
        return code
    print(format_console('ok', t('docker_swarm_registry_started', registry=registry)))
    print(format_console('info', t('docker_swarm_insecure_hint', registry=registry)))
    return 0


def cmd_push() -> int:
    root = _root()
    env = _env(root)
    registry = _registry(env)
    if not registry:
        print(format_console('error', t('docker_swarm_registry_missing')), file=sys.stderr)
        return 1
    docker = _docker()
    if not docker:
        print(format_console('error', t('docker_not_found_short')), file=sys.stderr)
        return 1
    image = f'{registry}/{IMAGE_NAME}'
    dockerfile = Path(__file__).resolve().parent / 'Dockerfile.python'
    code = _run([
        *docker, 'build',
        '-f', str(dockerfile),
        '--target', 'worker',
        '-t', image,
        str(root),
    ])
    if code != 0:
        return code
    code = _run([*docker, 'push', image])
    if code != 0:
        return code
    print(format_console('ok', t('docker_swarm_pushed', image=image)))
    return 0


def _label_workers(docker: str) -> None:
    result = subprocess.run(
        [*docker, 'node', 'ls', '--format', '{{.Hostname}} {{.ManagerStatus}}'],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        hostname = parts[0]
        status = parts[1] if len(parts) > 1 else ''
        if status in {'Leader', 'Reachable'}:
            continue
        subprocess.run(
            [*docker, 'node', 'update', '--label-add', 'ergo.worker=true', hostname],
            check=False,
        )


def cmd_deploy() -> int:
    root = _root()
    docker = _docker()
    if not docker:
        print(format_console('error', t('docker_not_found_short')), file=sys.stderr)
        return 1
    stack = write_stack(root)
    _label_workers(docker)
    code = _run([*docker, 'stack', 'deploy', '-c', str(stack), STACK_NAME])
    if code != 0:
        return code
    print(format_console('ok', t('docker_swarm_deployed', stack=STACK_NAME)))
    if _gpu_enabled(_env(root)):
        print(format_console('info', t('docker_swarm_gpu_hint')))
    return 0


def cmd_down() -> int:
    docker = _docker()
    if not docker:
        print(format_console('error', t('docker_not_found_short')), file=sys.stderr)
        return 1
    code = _run([*docker, 'stack', 'rm', STACK_NAME])
    if code != 0:
        return code
    print(format_console('ok', t('docker_swarm_removed', stack=STACK_NAME)))
    return 0


def _python(root: Path) -> Path | None:
    if sys.platform == 'win32':
        path = root / 'virtual_env' / 'python' / 'Scripts' / 'python.exe'
    else:
        path = root / 'virtual_env' / 'python' / 'bin' / 'python'
    return path if path.is_file() else None


def _watch_pid_path(root: Path) -> Path:
    return cache_dir(root) / 'celery_balance' / 'watch.pid'


def _pid_alive(pid: int) -> bool:
    """Чужой процесс тоже жив: отказ в сигнале — это не «такого pid нет»."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True


def _watch_cmdline(pid: int) -> str:
    proc = Path(f'/proc/{pid}/cmdline')
    if not proc.is_file():
        return ''
    try:
        return proc.read_bytes().replace(b'\x00', b' ').decode('utf-8', errors='replace')
    except OSError:
        return ''


def _project_watch_pids(root: Path) -> list[int]:
    """Наблюдатели плана этого дерева. Процесс в контейнере лежит по другому пути."""
    balance = root / 'core' / 'deployment' / 'celery_balance'
    cli_needle = str(balance / 'cli.py')
    supervise_needle = str(balance / 'supervise_watch.py')
    found: list[int] = []
    proc_root = Path('/proc')
    if not proc_root.is_dir():
        return found
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        cmdline = _watch_cmdline(pid)
        if supervise_needle in cmdline:
            found.append(pid)
            continue
        if cli_needle in cmdline and '--watch' in cmdline:
            found.append(pid)
    return found


def _signal_pid(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
        return
    except PermissionError:
        pass
    except OSError:
        return
    sudo = shutil.which('sudo')
    if not sudo:
        return
    flag = '-TERM' if sig == signal.SIGTERM else '-KILL'
    subprocess.run([sudo, '-n', 'kill', flag, str(pid)], check=False)


def _kill_pid(pid: int) -> bool:
    if not _pid_alive(pid):
        return False
    _signal_pid(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if _pid_alive(pid):
        _signal_pid(pid, signal.SIGKILL)
    return True


def _stop_watch(root: Path) -> None:
    path = _watch_pid_path(root)
    pids = set(_project_watch_pids(root))
    if path.is_file():
        try:
            recorded = int(path.read_text(encoding='utf-8').strip() or '0')
        except ValueError:
            recorded = 0
        cmdline = _watch_cmdline(recorded) if recorded else ''
        if recorded and (not cmdline or 'celery_balance' in cmdline):
            pids.add(recorded)
        path.unlink(missing_ok=True)
    stopped = False
    for pid in sorted(pids):
        if _kill_pid(pid):
            stopped = True
    if stopped:
        print(format_console('ok', t('celery_cluster_watch_stopped')))


def _ensure_watch(root: Path) -> None:
    python = _python(root)
    script = root / 'core' / 'deployment' / 'celery_balance' / 'cli.py'
    supervisor = root / 'core' / 'deployment' / 'celery_balance' / 'supervise_watch.py'
    if python is None or not script.is_file() or not supervisor.is_file():
        return
    _stop_watch(root)
    folder = ensure_dir(cache_dir(root) / 'celery_balance')
    logs = ensure_dir(root / 'logs')
    handle = (logs / 'celery-balance-watch.log').open('a', encoding='utf-8')
    # Супервизор сам перезапускает --watch; в pid — он, не дочерний круг.
    proc = subprocess.Popen(
        [str(python), str(supervisor), str(root), str(script)],
        cwd=str(root),
        stdout=handle,
        stderr=handle,
        start_new_session=True,
    )
    handle.close()
    (folder / 'watch.pid').write_text(str(proc.pid), encoding='utf-8')
    print(format_console('ok', t('celery_cluster_watch_started')))


def _mark_agent_ready(root: Path, ready: bool) -> None:
    path = ensure_dir(cache_dir(root) / 'celery_balance') / 'agent_ready'
    if ready:
        path.write_text('1\n', encoding='utf-8')
        return
    path.unlink(missing_ok=True)


def swarm_listen_recoverable(state: str, error: str, address_ready: bool) -> bool:
    """Менеджер не занял порт, потому что адреса ещё не было. Адрес уже есть — Docker можно поднять снова."""
    return (
        state.strip().lower() == 'error'
        and 'cannot assign requested address' in error.lower()
        and address_ready
    )


def _swarm_error_text(docker: list[str]) -> tuple[str, str]:
    result = subprocess.run(
        [*docker, 'info', '--format', '{{.Swarm.LocalNodeState}}|{{.Swarm.Error}}'],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return '', ''
    state, _, error = result.stdout.strip().partition('|')
    return state.strip().lower(), error.strip()


def _ipv4_assigned(host: str) -> bool:
    if not host:
        return False
    result = subprocess.run(
        ['ip', '-4', '-o', 'addr', 'show'],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    return f'inet {host}/' in result.stdout


def _install_docker_wait(root: Path) -> None:
    """Следующий старт Docker ждёт адрес менеджера. Иначе Swarm снова остаётся в ошибке до ручного перезапуска."""
    script = root / 'core' / 'deployment' / 'docker' / 'wait_swarm_address.sh'
    if not script.is_file():
        return
    try:
        script.chmod(0o755)
    except OSError:
        return
    target = Path('/etc/systemd/system/docker.service.d/ergo-swarm-address.conf')
    body = f'[Service]\nExecStartPre={script}\n'
    try:
        if target.is_file() and target.read_text(encoding='utf-8') == body:
            return
    except OSError:
        pass
    sudo = shutil.which('sudo')
    systemctl = shutil.which('systemctl')
    if not sudo or not systemctl:
        return
    folder = subprocess.run(
        [sudo, '-n', 'mkdir', '-p', str(target.parent)],
        check=False,
    )
    if folder.returncode != 0:
        return
    written = subprocess.run(
        [sudo, '-n', 'tee', str(target)],
        input=body,
        text=True,
        capture_output=True,
        check=False,
    )
    if written.returncode != 0:
        return
    subprocess.run([sudo, '-n', systemctl, 'daemon-reload'], check=False)


def _restart_dockerd() -> bool:
    systemctl = shutil.which('systemctl')
    if not systemctl:
        return False
    cmd = [systemctl, 'restart', 'docker']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is not None and result.returncode == 0:
        return True
    sudo = shutil.which('sudo')
    if not sudo:
        return False
    try:
        elevated = subprocess.run(
            [sudo, '-n', *cmd],
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return elevated.returncode == 0


def _ensure_swarm(docker: list[str], env: dict[str, str]) -> bool:
    if _swarm_active(docker):
        return True
    state, error = _swarm_error_text(docker)
    host = _manager_host(env, _registry(env))
    if not swarm_listen_recoverable(state, error, _ipv4_assigned(host)):
        return False
    if not _restart_dockerd():
        return False
    print(format_console('ok', t('celery_cluster_swarm_recovered')))
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if _swarm_active(docker):
            return True
        time.sleep(1)
    return _swarm_active(docker)


def _container_running(docker: list[str], name: str) -> bool:
    result = subprocess.run(
        [*docker, 'inspect', '-f', '{{.State.Running}}', name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == 'true'


def _swarm_active(docker: list[str]) -> bool:
    result = subprocess.run(
        [*docker, 'info', '--format', '{{.Swarm.LocalNodeState}}'],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == 'active'


def _image_has_prepare(docker: list[str], image: str) -> bool:
    probe = subprocess.run(
        [*docker, 'image', 'inspect', '--format', '{{.Id}}', image],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return False
    check = subprocess.run(
        [
            *docker, 'run', '--rm', '--entrypoint', 'test', image,
            '-f', '/app/core/deployment/scripts/prepare_swarm_packages.py',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return check.returncode == 0


def _wait_for_agent(root: Path, timeout: float = 45) -> bool:
    from celery_balance.cluster import connect, list_views

    client = connect(root)
    if client is None:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(not view.primary for view in list_views(client)):
            return True
        time.sleep(2)
    return False


def _run_balance_once(root: Path) -> None:
    python = _python(root)
    script = root / 'core' / 'deployment' / 'celery_balance' / 'cli.py'
    if python is None or not script.is_file():
        return
    subprocess.run([str(python), str(script)], cwd=str(root), check=False)


def sync_on_start() -> int:
    """Поднять наблюдатель плана и стек. Нет кластера или Swarm — обычный локальный старт."""
    from celery_balance.settings import load_settings

    root = _root()
    if not load_settings(root).cluster_enabled:
        return 0
    env = _env(root)
    registry = _registry(env)
    docker = _docker()
    _install_docker_wait(root)
    swarm_up = bool(registry and docker and _ensure_swarm(docker, env))
    if swarm_up and registry and docker and not _container_running(docker, REGISTRY_NAME):
        cmd_registry()
    image = f'{registry}/{IMAGE_NAME}' if registry else ''
    image_ready = bool(swarm_up and image and _image_has_prepare(docker, image))
    deployed = swarm_up and image_ready and cmd_deploy() == 0
    if not deployed:
        _mark_agent_ready(root, False)
        _ensure_watch(root)
        if swarm_up and not image_ready:
            print(format_console('warning', t('celery_cluster_image_missing', image=image)))
        elif registry and not swarm_up:
            print(format_console('warning', t('celery_cluster_swarm_skipped')))
        elif swarm_up and image_ready:
            print(format_console('warning', t('celery_cluster_swarm_skipped')))
        return 0
    _mark_agent_ready(root, True)
    _ensure_watch(root)
    if _wait_for_agent(root, timeout=90):
        _run_balance_once(root)
    return 0


def sync_on_stop() -> int:
    """Снять стек, пока Redis ещё жив. Нет Swarm — ничего не ломаем."""
    root = _root()
    _stop_watch(root)
    docker = _docker()
    if not docker or not _swarm_active(docker):
        return 0
    listed = subprocess.run(
        [*docker, 'stack', 'ls', '--format', '{{.Name}}'],
        capture_output=True,
        text=True,
        check=False,
    )
    names = {line.strip() for line in listed.stdout.splitlines()}
    if STACK_NAME not in names:
        return 0
    cmd_down()
    return 0
