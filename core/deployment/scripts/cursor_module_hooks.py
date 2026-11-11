"""Диспетчер hook-файлов модулей для событий Cursor.

Ищет modules/*/cursor_hooks.yaml и запускает команды выбранного события.
Имена модулей не зашиты. Сторонние пакеты не нужны: файл читает системный Python.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

_HOOK = "cursor_hooks.yaml"
_PYTHON = {"python", "python3"}


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _venv_python(root: Path) -> str | None:
    for relative in (
        "virtual_env/python/bin/python",
        "virtual_env/python/Scripts/python.exe",
    ):
        path = root / relative
        if path.is_file():
            return str(path)
    return None


def _commands(text: str, event: str) -> list[str]:
    found: list[str] = []
    active = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t")) and stripped.endswith(":"):
            active = stripped[:-1].strip() == event
            continue
        if active and stripped.startswith("- command:"):
            command = stripped.split(":", 1)[1].strip().strip("\"'")
            if command:
                found.append(command)
    return found


def _followup(stdout: str) -> str:
    raw = stdout.strip()
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(payload, dict):
        message = payload.get("followup_message")
        return message.strip() if isinstance(message, str) else ""
    return ""


def dispatch(event: str, stdin: str) -> int:
    root = _root()
    python = _venv_python(root)
    messages: list[str] = []
    modules = root / "modules"
    if modules.is_dir():
        for module_dir in sorted(path for path in modules.iterdir() if path.is_dir()):
            spec = module_dir / _HOOK
            if not spec.is_file():
                continue
            for command in _commands(spec.read_text(encoding="utf-8"), event):
                argv = shlex.split(command)
                if argv and argv[0] in _PYTHON and python:
                    argv[0] = python
                result = subprocess.run(
                    argv,
                    cwd=module_dir,
                    input=stdin,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                message = _followup(result.stdout)
                if message:
                    messages.append(message)
                elif result.returncode != 0:
                    detail = (result.stderr or result.stdout or "команда hook завершилась с ошибкой").strip()
                    messages.append(detail[:500])
    if messages:
        print(json.dumps({"followup_message": "\n".join(messages)}, ensure_ascii=False))
    else:
        print("{}")
    return 0


def main(argv: list[str]) -> int:
    event = "stop"
    if "--event" in argv:
        index = argv.index("--event")
        event = argv[index + 1] if index + 1 < len(argv) else "stop"
    return dispatch(event, sys.stdin.read())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
