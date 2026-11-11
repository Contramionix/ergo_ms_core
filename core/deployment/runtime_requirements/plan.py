"""Resolve requirements through the existing portable package registry."""

from pathlib import Path

from lifecycle.modules.catalog import ModuleCatalog
from packages.installer import install_package, is_platform_supported
from packages.registry import discover_packages

from .manifest import RuntimeRequirementsError, discover_requirements, model_entries, required_python_groups


def resolve_plan(root: Path):
    packages = discover_packages(root)
    requirements = discover_requirements(root)
    tools = {}
    models = []
    for manifest in requirements:
        for tool in manifest.tools:
            if tool.name not in packages:
                raise RuntimeRequirementsError(f'{manifest.path}: неизвестный инструмент {tool.name}')
            entry = tools.setdefault(tool.name, {'name': tool.name, 'required': False, 'modules': []})
            entry['required'] |= tool.required
            entry['modules'].append(manifest.module)
    consumers = {manifest.module for manifest in requirements}
    for module_dir in ModuleCatalog.from_env(root).iter_module_dirs():
        for provider in ('huggingface', 'ollama'):
            entries = model_entries(module_dir, provider)
            if entries:
                consumers.add(module_dir.name)
            models.extend({'provider': provider, 'module': module_dir.name, **entry} for entry in entries)
    return {'tools': list(tools.values()), 'models': models, 'python_groups': sorted(required_python_groups(root)), 'modules': sorted(consumers)}


def install_required_tools(root: Path, *, include_optional=False) -> int:
    plan = resolve_plan(root)
    packages = discover_packages(root)
    selected = [entry for entry in plan['tools'] if entry['required'] or include_optional]
    for entry in selected:
        if not is_platform_supported(packages[entry['name']]):
            raise RuntimeRequirementsError(f"Инструмент {entry['name']} не поддерживает текущую ОС")
    for entry in selected:
        code = install_package(root, entry['name'])
        if code:
            return code
    return 0
