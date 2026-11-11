"""Супервизор менеджерского celery-balance --watch: падение круга не оставляет кластер без плана."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_RESTART_DELAY_SEC = 5.0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print('usage: supervise_watch.py <project_root> <cli.py>', file=sys.stderr)
        return 2
    root = Path(args[0]).resolve()
    script = Path(args[1]).resolve()
    python = Path(sys.executable)
    if not script.is_file():
        print(f'supervise_watch: missing {script}', file=sys.stderr)
        return 2

    child: subprocess.Popen[bytes] | None = None
    stopping = False

    def _stop_child(signum: int, _frame) -> None:
        nonlocal stopping, child
        stopping = True
        proc = child
        if proc is None or proc.poll() is not None:
            raise SystemExit(0)
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            proc.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + 15
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.send_signal(signal.SIGKILL)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _stop_child)
    signal.signal(signal.SIGINT, _stop_child)

    while not stopping:
        child = subprocess.Popen(
            [str(python), str(script), '--watch'],
            cwd=str(root),
            start_new_session=True,
        )
        code = child.wait()
        child = None
        if stopping:
            return int(code or 0)
        time.sleep(_RESTART_DELAY_SEC)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
