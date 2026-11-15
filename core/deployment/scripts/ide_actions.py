"""Проверки, без которых в IDE нужно действие разработчика.

Печатает один JSON в stdout. Предупреждения — в stderr.
Имена модулей не зашиты: дополнительные проверки читаются из modules/*/ide_actions.yaml.
"""

from __future__ import annotations

import io
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


def _force_utf8_stdio() -> None:
    """На Windows канал процесса иначе в кодировке консоли, а IDE читает UTF-8."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
                continue
            except (OSError, ValueError):
                pass
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            continue
        setattr(
            sys,
            name,
            io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True),
        )


_force_utf8_stdio()

_DEPLOYMENT = Path(__file__).resolve().parents[1]
if str(_DEPLOYMENT) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT))

from cli_locale import t  # noqa: E402
from console_tags import format_console  # noqa: E402
from env_file_loader import apply_project_env_to_environ  # noqa: E402

_SAFE_REL = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_MIGRATION_TIMEOUT = 45
_MODULE_TIMEOUT = 20


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _warn(key: str, **params: str) -> None:
    print(format_console("warning", t(key, **params)), file=sys.stderr)


def _repo_rel(root: Path, path: Path) -> str:
    resolved = path.resolve()
    if resolved == root.resolve():
        return "."
    return resolved.relative_to(root.resolve()).as_posix()


def _repo_label(root: Path, rel: str) -> str:
    if rel == ".":
        return root.name
    return rel


def _safe_rel(value: str) -> str:
    text = value.strip().replace("\\", "/")
    if text == ".":
        return "."
    if not text:
        return ""
    if _SAFE_REL.fullmatch(text):
        return text
    return ""


def _git(repo: Path, *args: str, timeout: int = 15) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _is_git(path: Path) -> bool:
    if not path.exists():
        return False
    result = _git(path, "rev-parse", "--is-inside-work-tree")
    return bool(result and result.returncode == 0 and result.stdout.strip() == "true")


def _submodule_paths(root: Path) -> list[str]:
    spec = root / ".gitmodules"
    if not spec.is_file():
        return []
    found: list[str] = []
    try:
        text = spec.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("path"):
            continue
        _, _, raw = stripped.partition("=")
        rel = _safe_rel(raw)
        if rel:
            found.append(rel)
    return found


def _behind(repo: Path) -> int | None:
    result = _git(repo, "rev-list", "--count", "HEAD..@{upstream}")
    if result is None or result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip() or "0")
    except ValueError:
        return None


def git_actions(root: Path) -> list[dict]:
    behind: list[tuple[str, int]] = []
    repos = [root] if _is_git(root) else []
    for rel in _submodule_paths(root):
        path = root / rel
        if _is_git(path):
            repos.append(path)
    for repo in repos:
        count = _behind(repo)
        rel = _safe_rel(_repo_rel(root, repo))
        if count and rel:
            behind.append((rel, count))

    actions: list[dict] = []
    if behind:
        detail = ", ".join(f"{_repo_label(root, rel)} ({count})" for rel, count in behind)
        commands = [
            "git pull --ff-only" if rel == "." else f"git -C {rel} pull --ff-only"
            for rel, _count in behind
        ]
        actions.append({
            "id": "git-behind",
            "commands": commands,
            "detail": detail[:180],
        })
    return actions


def python_package_actions(root: Path) -> list[dict]:
    api = root / "core" / "api"
    api_src = api / "src"
    for entry in (api_src, api):
        entry_text = str(entry)
        if entry_text not in sys.path:
            sys.path.insert(0, entry_text)
    try:
        from commands.install import InstallCommand, _auto_extra_groups

        installer = InstallCommand()
        extra = _auto_extra_groups(root)
        root_data = installer._read_toml(root / "pyproject.toml")
        if not root_data:
            return [{"id": "python-packages", "commands": ["ergoms python-install"]}]
        module_configs = installer._scan_module_configs(root)
        module_only: dict = {}
        if module_configs:
            merged, _conflicts = installer._merge_dependencies(root_data, module_configs)
            root_deps = installer._get_poetry_deps(root_data)
            module_only = {
                pkg: constraint
                for pkg, constraint in merged.items()
                if pkg != "python" and pkg not in root_deps
            }
        unsatisfied = (
            installer._filter_unsatisfied_module_deps(module_only, root) if module_only else {}
        )
        if unsatisfied or not installer._core_lock_satisfied(root, extra_groups=extra):
            return [{"id": "python-packages", "commands": ["ergoms python-install"]}]
    except Exception:
        _warn("ide_actions_python_check_failed")
    return []


def npm_package_actions(root: Path) -> list[dict]:
    try:
        from lifecycle.host.ops import host_npm_deps_up_to_date

        if not host_npm_deps_up_to_date(root):
            return [{"id": "npm-packages", "commands": ["ergoms npm run install:all"]}]
    except Exception:
        _warn("ide_actions_npm_check_failed")
    return []


def _migration_names(root: Path) -> list[str] | None:
    api_src = root / "core" / "api" / "src"
    if not (api_src / "manage.py").is_file():
        return None
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--migrations-only"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_MIGRATION_TIMEOUT,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        _warn("ide_actions_migrations_skipped")
        return None
    if result.returncode != 0:
        _warn("ide_actions_migrations_skipped")
        tail = (result.stderr or "").strip().splitlines()
        if tail:
            line = tail[-1].strip()
            if line and "://" not in line and len(line) <= 120:
                print(line, file=sys.stderr)
        return None
    names = []
    for line in result.stdout.splitlines():
        text = line.strip()
        if text and " " not in text and "." in text:
            names.append(text)
    return names


def migration_actions(root: Path) -> list[dict]:
    names = _migration_names(root)
    if not names:
        return []
    return [{
        "id": "migrations",
        "commands": ["ergoms db-migrate"],
        "count": len(names),
        "detail": ", ".join(names[:8])[:180],
    }]


def migrations_only() -> int:
    """Дочерний процесс: имена неприменённых миграций, по одному в строке."""
    root = _root()
    api_dir = root / "core" / "api"
    os.chdir(api_dir)
    for entry in (root, api_dir):
        entry_text = str(entry)
        if entry_text not in sys.path:
            sys.path.insert(0, entry_text)
    try:
        from src.core.utils.auto_api.auto_config import get_env_deploy_type

        os.environ["DJANGO_SETTINGS_MODULE"] = get_env_deploy_type()
        from src.core.utils.django_cli import prepare_celery_for_django, prepare_lean_schema_django

        prepare_lean_schema_django()
        prepare_celery_for_django()
        import django
        from django.db import connections
        from django.db.migrations.executor import MigrationExecutor

        django.setup()
        executor = MigrationExecutor(connections["default"])
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception as exc:
        missing = getattr(exc, "name", None)
        detail = missing if isinstance(missing, str) and missing else type(exc).__name__
        if "://" not in detail and "password" not in detail.lower():
            print(detail, file=sys.stderr)
        return 3
    for migration, backwards in plan:
        if not backwards:
            print(f"{migration.app_label}.{migration.name}")
    return 0


def _commands_from_spec(text: str) -> list[str]:
    found: list[str] = []
    active = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t")) and stripped.endswith(":"):
            active = stripped[:-1].strip() == "check"
            continue
        if active and stripped.startswith("- command:"):
            command = stripped.split(":", 1)[1].strip().strip("\"'")
            if command and "\n" not in command and len(command) <= 500:
                found.append(command)
    return found


def _venv_python(root: Path) -> str | None:
    for relative in (
        "virtual_env/python/bin/python",
        "virtual_env/python/Scripts/python.exe",
    ):
        path = root / relative
        if path.is_file():
            return str(path)
    return None


def _parse_module_payload(stdout: str) -> list[dict]:
    raw = stdout.strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    rows = payload.get("actions") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    actions: list[dict] = []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        action_id = row.get("id")
        if not isinstance(action_id, str) or not _SAFE_ID.fullmatch(action_id):
            continue
        commands: list[str] = []
        raw_commands = row.get("commands")
        if isinstance(raw_commands, list):
            commands = [
                item.strip()
                for item in raw_commands
                if isinstance(item, str) and item.strip() and "\n" not in item and len(item) <= 500
            ][:8]
        elif isinstance(row.get("command"), str):
            command = row["command"].strip()
            if command and "\n" not in command and len(command) <= 500:
                commands = [command]
        if not commands:
            continue
        action = {"id": action_id, "commands": commands}
        title = row.get("title")
        detail = row.get("detail")
        if isinstance(title, str) and title.strip():
            action["title"] = title.strip()[:160]
        if isinstance(detail, str) and detail.strip():
            action["detail"] = detail.strip()[:180]
        actions.append(action)
    return actions


def module_actions(root: Path) -> list[dict]:
    from lifecycle.modules.catalog import parse_disabled_modules_raw

    modules = root / "modules"
    if not modules.is_dir():
        return []
    disabled = parse_disabled_modules_raw(os.environ.get("DISABLED_MODULES", ""))
    python = _venv_python(root)
    actions: list[dict] = []
    for module_dir in sorted(path for path in modules.iterdir() if path.is_dir()):
        if module_dir.name in disabled or module_dir.name.startswith("."):
            continue
        spec = module_dir / "ide_actions.yaml"
        if not spec.is_file():
            continue
        try:
            commands = _commands_from_spec(spec.read_text(encoding="utf-8"))
        except OSError:
            continue
        for command in commands:
            argv = shlex.split(command)
            if argv and argv[0] in {"python", "python3"} and python:
                argv[0] = python
            try:
                child_env = os.environ.copy()
                child_env["PYTHONIOENCODING"] = "utf-8"
                child_env["PYTHONUTF8"] = "1"
                result = subprocess.run(
                    argv,
                    cwd=module_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=_MODULE_TIMEOUT,
                    check=False,
                    env=child_env,
                )
            except (OSError, subprocess.TimeoutExpired):
                _warn("ide_actions_module_check_failed", path=module_dir.name)
                continue
            parsed = _parse_module_payload(result.stdout)
            if parsed:
                actions.extend(parsed)
            elif result.returncode != 0:
                _warn("ide_actions_module_check_failed", path=module_dir.name)
    return actions


def collect(root: Path) -> dict:
    actions: list[dict] = []
    actions.extend(python_package_actions(root))
    actions.extend(npm_package_actions(root))
    actions.extend(migration_actions(root))
    actions.extend(git_actions(root))
    actions.extend(module_actions(root))
    return {"actions": actions}


def main(argv: list[str]) -> int:
    root = _root()
    apply_project_env_to_environ(root)
    if "--migrations-only" in argv:
        return migrations_only()
    print(json.dumps(collect(root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
