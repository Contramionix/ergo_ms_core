"""Provider discovery and a rebuildable index; weights remain provider-owned."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import yaml

from huggingface.registry import load_resolved_models
from huggingface.snapshot import install as install_snapshot
from lifecycle.modules.catalog import ModuleCatalog
from project_layout import cache_dir, huggingface_snapshot_dir, huggingface_snapshot_ready, huggingface_trained_models_dir
from runtime_requirements import model_entries
from yaml_documents import load_unique_yaml


class ModelIndexError(ValueError):
    """A declaration, provider response or local artifact cannot be verified."""


@dataclass(frozen=True)
class Provider:
    name: str
    storage: Path
    script: Path | None = None


def discover_providers(root: Path) -> dict[str, Provider]:
    root = root.resolve()
    providers = {'huggingface': Provider('huggingface', huggingface_trained_models_dir(root))}
    for module in ModuleCatalog.from_env(root).iter_module_dirs():
        hook = module / 'model_providers.yaml'
        if not hook.is_file():
            continue
        try:
            data = load_unique_yaml(hook.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise ModelIndexError(f'Не удалось прочитать {hook}') from exc
        if (not isinstance(data, dict) or type(data.get('schema_version')) is not int
                or data['schema_version'] != 1 or data.get('module') != module.name
                or data.keys() - {'schema_version', 'module', 'providers'}
                or not isinstance(data.get('providers'), dict)):
            raise ModelIndexError(f'Некорректный hook провайдеров: {hook}')
        for name, entry in data['providers'].items():
            if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', name):
                raise ModelIndexError(f'Недопустимый провайдер: {name!r}')
            if name in providers:
                raise ModelIndexError(f'Повторный провайдер моделей: {name}')
            if (not isinstance(entry, dict) or entry.keys() != {'script', 'storage'}
                    or not all(isinstance(value, str) and value for value in entry.values())):
                raise ModelIndexError(f'Некорректное описание провайдера {name}')
            script = (module / entry['script']).resolve()
            storage = (root / entry['storage']).resolve()
            if (not script.is_relative_to(module.resolve()) or not script.is_file()
                    or script.suffix != '.py' or not storage.is_relative_to((root / 'virtual_env').resolve())
                    or storage == (root / 'virtual_env').resolve()):
                raise ModelIndexError(f'Пути провайдера {name} выходят за допустимые каталоги')
            providers[name] = Provider(name, storage, script)
    return providers


def _invoke(root, provider, action, name='', *, force=False):
    command = [sys.executable, str(provider.script), action, '--root', str(root)]
    if name:
        command += ['--model', name]
    if force:
        command += ['--force']
    try:
        result = subprocess.run(command, cwd=root, stdout=subprocess.PIPE,
                                stderr=None if action == 'install' else subprocess.PIPE, text=True,
                                encoding='utf-8', timeout=7200 if action == 'install' else 60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ModelIndexError(f'Провайдер {provider.name} недоступен') from exc
    if result.returncode:
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise ModelIndexError(f'Провайдер {provider.name}: операция {action} завершилась ошибкой')
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise ModelIndexError(f'Провайдер {provider.name} вернул некорректный JSON') from exc


def _record(provider, raw):
    if (not isinstance(raw, dict) or not isinstance(raw.get('name'), str) or not raw['name']
            or type(raw.get('required')) is not bool or type(raw.get('ready')) is not bool):
        raise ModelIndexError(f'Некорректная запись провайдера {provider.name}')
    local = raw.get('local_path')
    if raw['ready']:
        if not isinstance(local, str):
            raise ModelIndexError('Готовая модель не содержит локального пути')
        path = Path(local).resolve()
        if not path.is_relative_to(provider.storage.resolve()) or path == provider.storage.resolve() or not path.exists():
            raise ModelIndexError('Локальная модель находится вне хранилища провайдера')
        local = str(path)
    else:
        local = None
    return {'provider': provider.name, 'name': raw['name'], 'required': raw['required'],
            'ready': raw['ready'], 'local_path': local,
            'runtime_name': raw.get('runtime_name', raw['name']),
            'source_module': raw.get('source_module', ''), 'source_file': raw.get('source_file', ''),
            'reason': raw.get('reason', '' if raw['ready'] else 'model_missing')}


def _hf_record(root, name, **metadata):
    path = huggingface_snapshot_dir(root, name)
    ready = huggingface_snapshot_ready(path)
    return {'name': name, 'required': True, **metadata, 'ready': ready,
            'local_path': str(path) if ready else None,
            'reason': '' if ready else 'model_incomplete' if path.exists() else 'model_missing'}


def build_index(root: Path) -> dict:
    root = root.resolve()
    providers = discover_providers(root)
    unavailable = []
    for module in ModuleCatalog.from_env(root).iter_module_dirs():
        for provider in ('huggingface', 'ollama'):
            if provider not in providers and model_entries(module, provider):
                for entry in model_entries(module, provider):
                    name = entry.get('name') or entry.get('repo') or os.environ.get(entry.get('env', ''), '') or entry.get('default') or entry.get('env')
                    unavailable.append({'provider':provider, 'name':name, 'required':entry['required'],
                                        'ready':False, 'local_path':None, 'runtime_name':name,
                                        'source_module':module.name, 'source_file':'', 'reason':'provider_missing'})
    records = [_record(providers['huggingface'], _hf_record(root, model.repo_id,
                required=model.required, source_module=model.source_module, source_file=model.source_file))
               for model in load_resolved_models(root)]
    for provider in providers.values():
        if provider.script is None:
            continue
        response = _invoke(root, provider, 'list')
        if not isinstance(response, dict) or not isinstance(response.get('models'), list):
            raise ModelIndexError(f'Некорректный список моделей {provider.name}')
        records.extend(_record(provider, raw) for raw in response['models'])
    records.extend(unavailable)
    merged = {}
    for record in records:
        key = (record['provider'], record['name'])
        previous = merged.get(key)
        if previous:
            if previous['local_path'] != record['local_path'] or previous['ready'] != record['ready']:
                raise ModelIndexError('Провайдер вернул противоречащие ссылки на модель')
            previous['required'] |= record['required']
        else:
            merged[key] = record
    return {'schema_version': 1, 'models': sorted(merged.values(), key=lambda row:(row['provider'],row['name']))}


def resolve_local_model(root: Path, provider_name: str, name: str, *, allow_download=False, force=False) -> dict:
    root = root.resolve()
    provider = discover_providers(root).get(provider_name)
    if provider is None:
        raise ModelIndexError(f'Не загружен провайдер моделей: {provider_name}')
    raw = _hf_record(root, name) if provider.script is None else _invoke(root, provider, 'resolve', name)
    record = _record(provider, raw)
    if (not record['ready'] or force) and allow_download:
        if provider.script is None:
            if install_snapshot(root, name, force=force):
                raise ModelIndexError(f'Не удалось установить модель {provider_name}:{name}')
            raw = _hf_record(root, name)
        else:
            _invoke(root, provider, 'install', name, force=force)
            raw = _invoke(root, provider, 'resolve', name)
        record = _record(provider, raw)
    if not record['ready']:
        raise ModelIndexError(f'Нет проверенных локальных весов: {provider_name}:{name}')
    return record


def install_models(root: Path, *, include_optional=False) -> dict:
    index = build_index(root)
    for model in index['models']:
        if model['required'] or include_optional:
            resolve_local_model(root, model['provider'], model['name'], allow_download=True)
    index = build_index(root)
    write_index(root, index)
    return index


def write_index(root: Path, index: dict) -> Path:
    directory = cache_dir(root).resolve()
    if not directory.is_relative_to(root.resolve() / 'virtual_env'):
        raise ModelIndexError('Индекс моделей находится вне virtual_env')
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'model_index.json'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(index, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target
