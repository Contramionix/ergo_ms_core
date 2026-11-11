"""Strict runtime_requirements.yaml reader, independent of Django."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

import yaml

from lifecycle.modules.catalog import ModuleCatalog
from yaml_documents import load_unique_yaml

FILENAME = 'runtime_requirements.yaml'
_NAME = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$')
_PROVIDERS = {'huggingface', 'ollama'}


class RuntimeRequirementsError(ValueError):
    """Invalid, conflicting or unresolved runtime declaration."""


def _document(path):
    try:
        data = load_unique_yaml(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RuntimeRequirementsError(f'Не удалось прочитать {path}: {exc}') from exc
    if not isinstance(data, dict):
        raise RuntimeRequirementsError(f'{path}: ожидается объект YAML')
    return data


def _name(value, context):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise RuntimeRequirementsError(f'{context}: недопустимое имя {value!r}')
    return value


def _required(entry, context):
    value = entry.get('required', True)
    if not isinstance(value, bool):
        raise RuntimeRequirementsError(f'{context}: required должен быть boolean')
    return value


def _models(entries, context, *, provider=None):
    if not isinstance(entries, list):
        raise RuntimeRequirementsError(f'{context}: models должен быть списком')
    result = []
    for raw in entries:
        if not isinstance(raw, dict):
            raise RuntimeRequirementsError(f'{context}: модель должна быть объектом')
        entry = dict(raw)
        kind = entry.pop('provider', provider)
        if not isinstance(kind, str) or kind not in _PROVIDERS or (provider and kind != provider):
            raise RuntimeRequirementsError(f'{context}: неизвестный provider модели {kind!r}')
        allowed = {'env', 'default', 'required', 'name'} | ({'repo'} if kind == 'huggingface' else {'kind'})
        if entry.keys() - allowed:
            raise RuntimeRequirementsError(f'{context}: неизвестные поля модели {sorted(entry.keys() - allowed)}')
        for key, value in entry.items():
            if key != 'required' and not isinstance(value, str):
                raise RuntimeRequirementsError(f'{context}: {key} должен быть строкой')
            if key != 'required':
                entry[key] = value.strip()
        identity = entry.get('env') or entry.get('repo') or entry.get('name')
        if not identity:
            raise RuntimeRequirementsError(f'{context}: нужны repo/name или env модели')
        entry['required'] = _required(entry, context)
        if kind == 'huggingface' and 'name' in entry:
            if 'repo' in entry and entry['repo'] != entry['name']:
                raise RuntimeRequirementsError(f'{context}: repo и name указывают на разные модели')
            entry['repo'] = entry.pop('name')
        result.append({'provider': kind, **entry})
    return result


@dataclass(frozen=True)
class ToolRequirement:
    name: str
    required: bool = True


@dataclass(frozen=True)
class RuntimeRequirements:
    module: str
    path: Path
    tools: tuple[ToolRequirement, ...]
    models: tuple[dict, ...]
    python_groups: tuple[str, ...]


def load_manifest(module_dir: Path) -> RuntimeRequirements | None:
    path = module_dir / FILENAME
    if not path.is_file():
        return None
    data = _document(path)
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise RuntimeRequirementsError(f'{path}: поддерживается schema_version: 1')
    unknown = data.keys() - {'schema_version', 'module', 'tools', 'models', 'python'}
    if unknown:
        raise RuntimeRequirementsError(f'{path}: неизвестные поля {sorted(unknown)}')
    if data.get('module', module_dir.name) != module_dir.name:
        raise RuntimeRequirementsError(f'{path}: module не совпадает с каталогом')
    raw_tools = data.get('tools', [])
    if not isinstance(raw_tools, list):
        raise RuntimeRequirementsError(f'{path}: tools должен быть списком')
    tools = []
    for raw in raw_tools:
        entry = {'name': raw} if isinstance(raw, str) else raw
        if not isinstance(entry, dict) or entry.keys() - {'name', 'required'}:
            raise RuntimeRequirementsError(f'{path}: недопустимое описание инструмента')
        name = _name(entry.get('name'), str(path))
        if any(tool.name == name for tool in tools):
            raise RuntimeRequirementsError(f'{path}: повторный инструмент {name}')
        tools.append(ToolRequirement(name, _required(entry, str(path))))
    python = data.get('python', {})
    if not isinstance(python, dict) or python.keys() - {'groups'}:
        raise RuntimeRequirementsError(f'{path}: python допускает только groups')
    groups = python.get('groups', [])
    if not isinstance(groups, list):
        raise RuntimeRequirementsError(f'{path}: python.groups должен быть списком')
    groups = tuple(_name(group, str(path)) for group in groups)
    if len(groups) != len(set(groups)):
        raise RuntimeRequirementsError(f'{path}: повторная Python-группа')
    return RuntimeRequirements(module_dir.name, path, tuple(tools), tuple(_models(data.get('models', []), str(path))), groups)


def discover_requirements(root: Path) -> tuple[RuntimeRequirements, ...]:
    manifests = []
    for module_dir in ModuleCatalog.from_env(root).iter_module_dirs():
        manifest = load_manifest(module_dir)
        if manifest is not None:
            manifests.append(manifest)
    return tuple(manifests)


def required_python_groups(root: Path) -> frozenset[str]:
    groups = {group for manifest in discover_requirements(root) for group in manifest.python_groups}
    if groups:
        try:
            data = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise RuntimeRequirementsError('Не удалось прочитать корневой pyproject.toml') from exc
        declared = data
        for key in ('tool', 'poetry', 'group'):
            declared = declared.get(key, {})
            if not isinstance(declared, dict):
                raise RuntimeRequirementsError('Некорректная структура Python-групп в корневом pyproject.toml')
        missing = groups - declared.keys()
        if missing:
            raise RuntimeRequirementsError(f'Неизвестные Python-группы ядра: {sorted(missing)}')
    return frozenset(groups)


def model_entries(module_dir: Path, provider: str) -> list[dict]:
    """Merge old hook and new manifest; conflicting declarations fail closed."""
    manifest = load_manifest(module_dir)
    entries = [dict(entry) for entry in manifest.models if entry['provider'] == provider] if manifest else []
    legacy = module_dir / f'{provider}_models.yaml'
    if legacy.is_file():
        data = _document(legacy)
        if data.get('module', module_dir.name) != module_dir.name:
            raise RuntimeRequirementsError(f'{legacy}: module не совпадает с каталогом')
        entries += _models(data.get('models', []), str(legacy), provider=provider)
    by_key = {}
    for entry in entries:
        entry.pop('provider', None)
        key = ('env', entry['env']) if entry.get('env') else ('name', entry.get('repo') or entry.get('name'))
        previous = by_key.get(key)
        if previous is not None and previous != entry:
            raise RuntimeRequirementsError(f'{module_dir}: противоречащие объявления модели {key[1]}')
        by_key[key] = entry
    return list(by_key.values())
