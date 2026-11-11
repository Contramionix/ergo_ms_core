"""Непрерывная подстройка без restart-loop."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from cli_locale import t
from console_tags import format_console

from celery_balance.apply import apply_plans, should_skip_change
from celery_balance.constants import MODE_AUTO, MODE_RECOMMEND, ROLE_MANAGER
from celery_balance.report import print_report
from celery_balance.service import collect_snapshot, persist_snapshot, previous_concurrency


def run_watch(
    project_root: Path,
    *,
    dry_run: bool,
    as_json: bool,
    show_cluster: bool = False,
) -> int:
    _start_plan_keepalive(project_root, dry_run=dry_run)
    while True:
        try:
            _watch_once(
                project_root,
                dry_run=dry_run,
                as_json=as_json,
                show_cluster=show_cluster,
            )
        except Exception as exc:  # noqa: BLE001 — круг не должен убивать процесс
            print(format_console('warning', t('celery_balance_watch_error', error=str(exc))))
            time.sleep(5.0)
            continue
        from celery_balance.settings import load_settings

        time.sleep(load_settings(project_root).watch_interval_sec)


def _watch_once(
    project_root: Path,
    *,
    dry_run: bool,
    as_json: bool,
    show_cluster: bool,
) -> None:
    # Каталог читается с диска каждый круг: процесс живёт сутками и иначе держит старый placement.
    from celery_balance.footprint_loader import load_footprints

    load_footprints.cache_clear()
    snapshot = collect_snapshot(project_root)
    from celery_balance.cluster import sync_cluster

    sync_cluster(project_root, snapshot, write=not dry_run)
    prev = previous_concurrency(project_root)
    skip_all = True
    for plan in snapshot.plans:
        if not should_skip_change(
            prev.get(plan.name),
            plan.concurrency,
            snapshot.settings.hysteresis_ratio,
        ):
            skip_all = False
            break

    apply_overlay = (
        not dry_run
        and snapshot.settings.mode in {MODE_AUTO, MODE_RECOMMEND}
    )
    if apply_overlay and not skip_all:
        persist_snapshot(project_root, snapshot)
    elif apply_overlay and snapshot.settings.mode == MODE_RECOMMEND:
        persist_snapshot(project_root, snapshot)

    result = apply_plans(
        project_root,
        snapshot.plans,
        settings=snapshot.settings,
        previous=prev,
        dry_run=dry_run or skip_all,
        write_overlay=bool(snapshot.overlay_path),
    )
    if as_json:
        import json

        payload = snapshot.to_dict()
        payload['watch'] = {
            'skipped': skip_all,
            'live_applied': result.live_applied,
            'needs_restart': result.needs_restart,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if skip_all:
            print(format_console('info', t('celery_balance_watch_skip')))
        print_report(
            snapshot,
            dry_run=dry_run,
            show_cluster=show_cluster or snapshot.settings.cluster_enabled,
        )
        if result.needs_restart and snapshot.settings.mode == MODE_AUTO:
            print(format_console('info', t('celery_balance_restart_hint')))
    _requeue_orphaned(project_root)


def _start_plan_keepalive(project_root: Path, *, dry_run: bool) -> None:
    """Пока sync_cluster считает, уже опубликованный план не должен протухнуть."""
    if dry_run:
        return

    def _loop() -> None:
        while True:
            interval = 15.0
            try:
                from celery_balance.cluster import connect, renew_plans
                from celery_balance.settings import load_settings

                settings = load_settings(project_root)
                interval = max(15.0, settings.watch_interval_sec / 2.0)
                if (
                    settings.cluster_enabled
                    and settings.cluster_role == ROLE_MANAGER
                ):
                    client = connect(project_root)
                    if client is not None:
                        renew_plans(client, settings.plan_ttl_sec)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(interval)

    threading.Thread(
        target=_loop,
        name='celery-plan-keepalive',
        daemon=True,
    ).start()


def _requeue_orphaned(project_root: Path) -> None:
    """Сигнал воркеру не вернул задачу. Здесь её забирает общий механизм."""
    from celery_requeue.restore import requeue_orphaned

    format_result = None
    try:
        from celery_requeue_unacked import format_result as _format_result
        format_result = _format_result
    except ImportError:
        format_result = None
    try:
        result = requeue_orphaned(project_root)
    except Exception:
        print(format_console('warning', t('celery_requeue_failed')))
        return
    if not result.restored:
        return
    if format_result is not None:
        print(format_result(result))
        return
    print(format_console('ok', t('celery_requeue_done', count=result.restored, queues='')))
