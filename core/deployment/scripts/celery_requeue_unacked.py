"""Вернуть в очередь задачи Celery, чей воркер уже не держит их.

Вызов: ergoms celery-requeue
После остановки воркера то же делает наблюдатель и ExecStopPost службы.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_DEPLOYMENT_DIR = Path(__file__).resolve().parents[1]
if str(_DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOYMENT_DIR))

from cli_locale import t  # noqa: E402
from console_tags import format_console  # noqa: E402
from celery_requeue.restore import RequeueResult, requeue_orphaned  # noqa: E402


def project_root_from_here() -> Path:
    return _DEPLOYMENT_DIR.parent.parent


def format_result(result: RequeueResult) -> str:
    if result.skipped == 'not-redis':
        return format_console('skip', t('celery_requeue_not_redis'))
    if result.skipped == 'redis-down':
        return format_console('warning', t('celery_requeue_redis_down'))
    if result.restored:
        queues = ', '.join(
            f'{name} {count}'
            for name, count in sorted(result.by_queue.items(), key=lambda item: (-item[1], item[0]))
        )
        return format_console('ok', t('celery_requeue_done', count=result.restored, queues=queues))
    if result.skipped == 'unknown-consumers':
        return format_console('warning', t('celery_requeue_unknown'))
    return format_console('ok', t('celery_requeue_none'))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='requeue orphaned celery tasks')
    parser.add_argument('--root', default='')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else project_root_from_here()
    if not root.is_dir():
        print(format_console('error', t('project_dir_not_found', root=root)), file=sys.stderr)
        return 1
    try:
        result = requeue_orphaned(root)
    except Exception:
        print(format_console('warning', t('celery_requeue_failed')), file=sys.stderr)
        return 0
    if args.quiet and result.restored == 0 and result.skipped != 'redis-down':
        return 0
    print(format_result(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
