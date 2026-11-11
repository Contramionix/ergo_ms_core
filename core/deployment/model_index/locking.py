"""Serialize installation of one model across processes without extra dependencies."""

from contextlib import contextmanager
import errno
import hashlib
import os
from pathlib import Path
import time

from project_layout import cache_dir


@contextmanager
def model_lock(root: Path, provider: str, name: str, *, timeout=7200):
    directory = cache_dir(root) / 'model_locks'
    if not directory.resolve().is_relative_to(root.resolve() / 'virtual_env'):
        raise ValueError('Блокировка модели находится вне virtual_env')
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((provider + '\0' + name).encode()).hexdigest()
    deadline = time.monotonic() + timeout
    with (directory / (key + '.lock')).open('a+b') as stream:
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b'0')
            stream.flush()
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError('Истекло ожидание установки модели') from exc
                time.sleep(0.1)
        yield  # Closing the descriptor also releases the OS lock on failures.
