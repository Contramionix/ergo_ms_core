"""
Слой абстракции для ОС-зависимой логики в MCP-обёртках (.cursor).

Для тестов: set_impl(mock) / reset_impl()
"""

import subprocess
import sys
import shutil
from pathlib import Path
from typing import Optional

_impl = None


def _get_impl():
    global _impl
    if _impl is None:
        _impl = WindowsImpl() if sys.platform == 'win32' else LinuxImpl()
    return _impl


def set_impl(impl):
    global _impl
    _impl = impl


def reset_impl():
    global _impl
    _impl = None


def _portable_npx_path() -> Optional[Path]:
    """npx из portable Node, не из PATH процесса Cursor."""
    root = Path(__file__).resolve().parent.parent
    base = root / 'virtual_env' / 'packages' / 'nodejs'
    if sys.platform == 'win32':
        candidate = base / 'npx.cmd'
    else:
        candidate = base / 'bin' / 'npx'
    return candidate if candidate.is_file() else None


class WindowsImpl:
    def get_venv_python_path(self, venv_dir: Path) -> Path:
        return venv_dir / 'Scripts' / 'python.exe'

    def get_background_popen_kwargs(self) -> dict:
        return {'creationflags': subprocess.CREATE_NO_WINDOW}

    def get_npx_executable(self) -> Optional[str]:
        portable = _portable_npx_path()
        if portable is not None:
            return str(portable)
        return shutil.which('npx.cmd') or shutil.which('npx')


class LinuxImpl:
    def get_venv_python_path(self, venv_dir: Path) -> Path:
        p = venv_dir / 'bin' / 'python3'
        if p.exists():
            return p
        return venv_dir / 'bin' / 'python'

    def get_background_popen_kwargs(self) -> dict:
        return {'start_new_session': True}

    def get_npx_executable(self) -> Optional[str]:
        portable = _portable_npx_path()
        if portable is not None:
            return str(portable)
        return shutil.which('npx')


def get_venv_python_path(venv_dir: Path) -> Path:
    return _get_impl().get_venv_python_path(venv_dir)


def get_background_popen_kwargs() -> dict:
    return _get_impl().get_background_popen_kwargs()


def get_npx_executable() -> Optional[str]:
    return _get_impl().get_npx_executable()
