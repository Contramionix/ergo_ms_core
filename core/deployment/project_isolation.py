"""Early, module-independent validation of isolated installation resources."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from env_file_loader import load_project_env
from cli_locale import t


class IsolationError(RuntimeError):
    """An isolated installation points to unchecked resources."""


def _path(root: Path, value: str) -> Path:
    path = Path(value)
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def _inside(path: Path, parent: Path) -> bool:
    return path.resolve().is_relative_to(parent.resolve())


def _endpoint(host, port) -> tuple[str, int]:
    if not isinstance(host, str) or not host.strip() or type(port) is bool:
        raise IsolationError(t('isolation_endpoint'))
    try:
        number = int(port)
    except (TypeError, ValueError) as exc:
        raise IsolationError(t('isolation_port')) from exc
    if not 1 <= number <= 65535:
        raise IsolationError(t('isolation_port_range'))
    return host.lower().strip(), number


def _endpoints(section: dict) -> set[tuple[str, int]]:
    rows = section.get('endpoints')
    if not isinstance(rows, list) or not rows:
        raise IsolationError(t('isolation_endpoints_missing'))
    result = set()
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise IsolationError(t('isolation_endpoint_shape'))
        result.add(_endpoint(*row))
    return result


def _manifest(root: Path, location: Path) -> dict:
    try:
        data = json.loads(location.read_text(encoding='utf-8'))
        marker = (root / 'virtual_env/pilot/identity').read_text(encoding='utf-8').strip()
        if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] not in (1, 2):
            raise ValueError('unsupported schema')
        identity = data.get('pilot_id')
        if not isinstance(identity, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{7,62}', identity) or identity != marker:
            raise ValueError('invalid identity')
        database = data['database']
        redis = data['redis']
        if not isinstance(database, dict) or not isinstance(redis, dict):
            raise ValueError('invalid resource declaration')
        # Resource names belong to this installation, not merely to a reachable server.
        if database.get('name') != identity or database.get('user') != identity or data.get('compose_project') != identity:
            raise ValueError('resource identity differs')
        _endpoints(database)
        _endpoints(redis)
        if data['schema_version'] == 2:
            policy = data.get('environment')
            if not isinstance(policy, dict) or not policy or any(
                not isinstance(key, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key) or not isinstance(value, str)
                for key, value in policy.items()
            ):
                raise ValueError('invalid environment constraints')
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise IsolationError(t('isolation_manifest')) from exc


def _database_sections(sections, manifest: dict) -> None:
    expected = manifest['database']
    sql_endpoints = _endpoints(expected)
    redis_endpoints = _endpoints(manifest['redis'])
    if not isinstance(sections, dict) or 'default' not in sections:
        raise IsolationError(t('isolation_default_missing'))
    for alias, config in sections.items():
        if not isinstance(config, dict):
            raise IsolationError(t('isolation_section'))
        endpoint = _endpoint(config.get('host'), config.get('port'))
        engine = str(config.get('engine', '')).lower()
        if engine == 'redis':
            if endpoint not in redis_endpoints or not config.get('password'):
                raise IsolationError(t('isolation_redis', alias=alias))
        elif engine not in {'postgresql', 'postgres', 'django.db.backends.postgresql'} or (
            config.get('name') != expected['name'] or config.get('user') != expected['user']
            or endpoint not in sql_endpoints or not config.get('password')
        ):
            raise IsolationError(t('isolation_database', alias=alias))


def validate_project(root: Path, *, environ=None, required=False) -> dict | None:
    """Validate connections and paths before Django, Compose or destructive work."""
    root = root.resolve()
    env = load_project_env(root)
    env.update(os.environ if environ is None else environ)
    pointer = env.get('ERGO_PILOT_MANIFEST', '')
    directory = root / 'virtual_env/pilot'
    if not pointer:
        if any((directory / name).exists() for name in ('identity', 'isolation.json')):
            raise IsolationError(t('isolation_pointer_missing'))
        if required:
            raise IsolationError(t('isolation_required'))
        return None
    location = _path(root, pointer)
    if not _inside(directory, root) or not _inside(location, directory):
        raise IsolationError(t('isolation_manifest_path'))
    manifest = _manifest(root, location)
    # Version 1 predates declarative constraints; retain its conservative defaults.
    policy = manifest.get('environment', {
        'ERGO_RUNTIME': 'docker', 'API_DATABASE_CONN_MAX_AGE': '0',
        'BRIDGE_TRANSPORT': 'local', 'BRIDGE_SERVICE_URLS': '',
    })
    for key, expected in policy.items():
        actual = env.get(key, 'local' if key == 'BRIDGE_TRANSPORT' else '')
        if actual != expected:
            raise IsolationError(t('isolation_environment', key=key))
    if env.get('DOCKER_COMPOSE_PROJECT') != manifest['compose_project'] or (
        env.get('COMPOSE_PROJECT_NAME', manifest['compose_project']) != manifest['compose_project']
    ):
        raise IsolationError(t('isolation_compose'))

    import yaml

    from yaml_documents import load_unique_yaml

    paths = {root / 'databases.yaml'}
    if env.get('ERGO_DATABASES_YAML'):
        paths.add(_path(root, env['ERGO_DATABASES_YAML']))
    composed = root / 'core/deployment/docker/.compose.databases.yaml'
    if composed.is_file():
        paths.add(composed)
    for path in paths:
        if not _inside(path, root):
            raise IsolationError(t('isolation_connections_path'))
        try:
            document = load_unique_yaml(path.read_text(encoding='utf-8'))
            _database_sections(document['databases'], manifest)
        except (OSError, UnicodeError, yaml.YAMLError, KeyError, TypeError) as exc:
            raise IsolationError(t('isolation_connections')) from exc
    for key, relative in (
        ('MEDIA_STORAGE_PATH', 'media'), ('MEDIA_ROOT', 'media'),
        ('ERGO_LOGS_DIR', 'logs'), ('GENERATED_DOCUMENTS_DIR', 'media/generated_docs'),
    ):
        candidate = _path(root, env.get(key) or relative)
        if candidate == root or not _inside(candidate, root):
            raise IsolationError(t('isolation_storage_path', key=key))
        if key in {'MEDIA_STORAGE_PATH', 'MEDIA_ROOT'} and candidate != (root / 'media').resolve():
            raise IsolationError(t('isolation_media'))
    for relative in ('media', 'virtual_env/backups', 'virtual_env/pilot', 'virtual_env/cache', 'virtual_env/npm', 'logs'):
        if not _inside(root / relative, root):
            raise IsolationError(t('isolation_directory', relative=relative))
    for key in ('CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND'):
        if env.get(key):
            try:
                url = urlsplit(env[key])
                valid = url.scheme == 'redis' and _endpoint(url.hostname, url.port or 6379) in _endpoints(manifest['redis'])
            except (ValueError, IsolationError):
                valid = False
            if not valid:
                raise IsolationError(t('isolation_celery', key=key))
    return manifest


def validate_django(root: Path, settings, *, required=True) -> dict:
    manifest = validate_project(root, required=required)
    if manifest is None:
        return {}
    expected = manifest['database']
    for alias, config in settings.DATABASES.items():
        if (
            config.get('ENGINE') != 'django.db.backends.postgresql'
            or config.get('NAME') not in {expected['name'], f'test_{expected["name"]}'}
            or config.get('USER') != expected['user']
            or _endpoint(config.get('HOST'), config.get('PORT')) not in _endpoints(expected)
            or config.get('TEST', {}).get('MIRROR')
            or config.get('CONN_MAX_AGE', 0) != 0
        ):
            raise IsolationError(t('isolation_django_database', alias=alias))
    if Path(settings.MEDIA_ROOT).resolve() != (root.resolve() / 'media').resolve():
        raise IsolationError(t('isolation_django_media'))
    return manifest
