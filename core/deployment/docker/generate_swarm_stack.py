"""Стек Swarm для воркеров Celery. Файл генерируется, в git не входит."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

DOCKER_DIR = Path(__file__).resolve().parent
DEPLOYMENT_DIR = DOCKER_DIR.parent
PROJECT_ROOT = DEPLOYMENT_DIR.parent.parent
OUTPUT = DOCKER_DIR / 'docker-stack.workers.generated.yml'

if str(DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOYMENT_DIR))

from cli_locale import t  # noqa: E402


_ON = frozenset({'1', 'true', 'yes', 'on'})


def ollama_enabled(env: dict[str, str]) -> bool:
    return str(env.get('DOCKER_SWARM_OLLAMA') or '').strip().lower() in _ON


def ollama_bind(env: dict[str, str]) -> str:
    """Хост:порт из DOCKER_SWARM_OLLAMA_BIND. Без порта — 11434."""
    raw = str(env.get('DOCKER_SWARM_OLLAMA_BIND') or '').strip()
    if not raw:
        return ''
    if '://' in raw:
        raw = raw.split('://', 1)[1]
    raw = raw.rstrip('/')
    if ':' not in raw:
        raw = f'{raw}:11434'
    return raw


def _config_source(prefix: str, path: str) -> str:
    """Имя config с хешем файла: Swarm не даёт менять config с тем же именем."""
    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
    except OSError:
        return prefix
    return f'{prefix}_{digest}'


def render_stack(
    *,
    image: str,
    manager_host: str,
    databases_file: str,
    env_file: str,
    gpu: bool,
    media_url: str = '',
    media_internal_key: str = '',
    ollama_url: str = '',
    db_port: str = '5432',
    ollama_service: bool = False,
    ollama_bind: str = '',
    ollama_image: str = '',
) -> str:
    gpu_block = ''
    if gpu:
        gpu_block = """
      resources:
        reservations:
          generic_resources:
            - discrete_resource_spec:
                kind: NVIDIA-GPU
                value: 1
"""
    remote_env = ''
    if media_url:
        remote_env += (
            '      ERGO_MEDIA: remote\n'
            f'      MEDIA_API_INTERNAL_URL: "{media_url}"\n'
        )
        if media_internal_key:
            remote_env += f'      MEDIA_API_INTERNAL_KEY: "{media_internal_key}"\n'
    if ollama_service and ollama_bind:
        # Файл модуля в образе переписывает OLLAMA_BASE_URL. OVERRIDE слияние не трогает.
        ollama_url = f'http://{ollama_bind}'
    if ollama_url:
        remote_env += (
            f'      OLLAMA_BASE_URL: "{ollama_url}"\n'
            f'      OLLAMA_BASE_URL_OVERRIDE: "{ollama_url}"\n'
        )
    dotenv_name = _config_source('ergo_dotenv', env_file)
    databases_name = _config_source('ergo_databases', databases_file)
    service_configs = f"""    configs:
      - source: {dotenv_name}
        target: /app/.env
      - source: {databases_name}
        target: /app/databases.yaml
"""
    # Одна карта на узле. Её резервирует Ollama, если сервис включён, иначе воркер.
    worker_gpu = '' if ollama_service else gpu_block
    ollama_volume = ''
    ollama_block = ''
    if ollama_service and ollama_bind and ollama_image:
        ollama_block = f"""  ergo-ollama:
    image: {ollama_image}
    environment:
      OLLAMA_HOST: "{ollama_bind}"
      OLLAMA_NO_CLOUD: "1"
      NVIDIA_VISIBLE_DEVICES: all
    networks:
      - host
    volumes:
      - ergo_ollama_models:/root/.ollama
    deploy:
      mode: global
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.labels.ergo.worker == true
{gpu_block}"""
        ollama_volume = '  ergo_ollama_models:\n'
    return f"""# Автогенерация: ergoms docker-swarm-deploy (не редактировать вручную)
services:
  ergo-celery-agent:
    image: {image}
    environment:
      CELERY_CLUSTER: "on"
      CELERY_CLUSTER_ROLE: agent
      ERGO_NODE_ID: "{{{{.Node.Hostname}}}}"
      DOCKER_ENABLED: "true"
      ERGO_BROKER: redis
      REDIS_HOST: {manager_host}
      ERGO_DOCKER_DB_HOST: {manager_host}
      ERGO_DOCKER_DB_PORT: "{db_port}"
      DOCKER_DATABASE: container
      DOCKER_PROFILE_POSTGRES: "true"
      ERGO_DATABASES_YAML: /app/databases.yaml
{service_configs}    command: ["python", "core/deployment/celery_balance/cli.py", "--watch"]
    deploy:
      mode: global
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.labels.ergo.worker == true
  ergo-celery-worker:
    image: {image}
    environment:
      CELERY_CLUSTER: "on"
      CELERY_CLUSTER_ROLE: agent
      ERGO_NODE_ID: "{{{{.Node.Hostname}}}}"
      DOCKER_ENABLED: "true"
      ERGO_BROKER: redis
      REDIS_HOST: {manager_host}
      ERGO_DOCKER_DB_HOST: {manager_host}
      ERGO_DOCKER_DB_PORT: "{db_port}"
      DOCKER_DATABASE: container
      DOCKER_PROFILE_POSTGRES: "true"
      ERGO_DATABASES_YAML: /app/databases.yaml
      NVIDIA_VISIBLE_DEVICES: all
{remote_env}{service_configs}    command: ["sh", "-c", "if [ -f /app/core/deployment/scripts/prepare_swarm_packages.py ]; then python /app/core/deployment/scripts/prepare_swarm_packages.py || exit 1; fi; exec python /app/core/api/scripts/start_celery_worker.py"]
    networks:
      - host
    volumes:
      - ergo_worker_cache:/app/virtual_env/cache
      - ergo_worker_packages:/app/virtual_env/packages
      - /var/run/docker.sock:/var/run/docker.sock
    stop_grace_period: 60s
    deploy:
      mode: global
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.labels.ergo.worker == true
{worker_gpu}{ollama_block}networks:
  host:
    external: true
    name: host
volumes:
  ergo_worker_cache:
  ergo_worker_packages:
{ollama_volume}configs:
  {dotenv_name}:
    file: {env_file}
  {databases_name}:
    file: {databases_file}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate Swarm worker stack')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--image', required=True)
    parser.add_argument('--manager-host', required=True)
    parser.add_argument('--databases-file', required=True)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--gpu', action='store_true')
    parser.add_argument('--media-url', default='')
    parser.add_argument('--ollama-url', default='')
    parser.add_argument('--ollama-service', action='store_true')
    parser.add_argument('--ollama-bind', default='')
    parser.add_argument('--ollama-image', default='')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    content = render_stack(
        image=args.image,
        manager_host=args.manager_host,
        databases_file=args.databases_file,
        env_file=args.env_file,
        gpu=args.gpu,
        media_url=args.media_url,
        ollama_url=args.ollama_url,
        ollama_service=args.ollama_service,
        ollama_bind=args.ollama_bind,
        ollama_image=args.ollama_image,
    )
    args.output.write_text(content, encoding='utf-8')
    if not args.quiet:
        print(t('docker_swarm_stack_written', output=args.output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
