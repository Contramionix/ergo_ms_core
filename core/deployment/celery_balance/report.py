"""Текстовый отчёт celery-balance для консоли."""

from __future__ import annotations

from cli_locale import t
from console_tags import format_console

from celery_balance.constants import MODE_AUTO, MODE_OFF
from celery_balance.service import BalanceSnapshot


def print_report(snapshot: BalanceSnapshot, *, dry_run: bool, show_cluster: bool = False) -> None:
    settings = snapshot.settings
    budget = snapshot.budget
    gpu = budget.gpu
    gpu_text = (
        t(
            'celery_balance_gpu_yes',
            count=gpu.count,
            free=f'{gpu.vram_free_mb:.0f}',
            total=f'{gpu.vram_total_mb:.0f}',
        )
        if gpu.available
        else t('celery_balance_gpu_no')
    )
    mode_note = t('celery_balance_dry_run') if dry_run else settings.mode
    print(
        format_console(
            'info',
            t(
                'celery_balance_header',
                mode=settings.mode,
                note=mode_note,
            ),
        )
    )
    print(
        t(
            'celery_balance_host_line',
            ram_total=f'{budget.ram_total_mb:.0f}',
            ram_percent=f'{budget.ram_percent:.0f}',
            cpu=f'{budget.cpu_count:g}',
            source=budget.source,
            gpu=gpu_text,
        )
    )
    print(
        t(
            'celery_balance_budget_line',
            ram=f'{budget.celery_ram_budget_mb:.0f}',
            cpu=f'{budget.celery_cpu_budget:g}',
            reserve=f'{budget.reserve_memory_mb:.0f}',
        )
    )

    if snapshot.queues.queues:
        parts = []
        for item in snapshot.queues.queues:
            depth = '?' if item.depth is None else str(item.depth)
            parts.append(f'{item.name}={depth}')
        print(
            t(
                'celery_balance_queues_line',
                broker=snapshot.queues.broker,
                items=', '.join(parts),
            )
        )
    else:
        print(t('celery_balance_queues_empty'))

    forecast = snapshot.forecast
    print(
        t(
            'celery_balance_forecast_line',
            pending=f'{forecast.pending_sec:.0f}',
            beat=forecast.beat_entries,
        )
    )

    for plan in snapshot.plans:
        yaml_c = plan.yaml_concurrency if plan.yaml_concurrency is not None else '-'
        print(
            t(
                'celery_balance_worker_line',
                name=plan.name,
                yaml=yaml_c,
                planned=plan.concurrency,
                prefetch=plan.prefetch_multiplier,
                pool=plan.pool,
            )
        )
        for reason in plan.reasons:
            print(f'  {reason}')
        if plan.mixed_gpu_light:
            print(format_console('info', t('celery_balance_mixed_gpu_hint', name=plan.name)))

    if show_cluster or snapshot.settings.cluster_enabled:
        _print_cluster(snapshot)

    if snapshot.overlay_path:
        print(
            format_console(
                'ok',
                t('celery_balance_overlay_written', path=snapshot.overlay_path),
            )
        )
    elif dry_run:
        print(format_console('info', t('celery_balance_no_apply')))
    elif settings.mode == MODE_OFF:
        print(format_console('info', t('celery_balance_mode_off')))
    elif settings.mode != MODE_AUTO:
        print(format_console('info', t('celery_balance_recommend_only')))


def _print_cluster(snapshot: BalanceSnapshot) -> None:
    if not snapshot.settings.cluster_enabled:
        print(format_console('info', t('celery_balance_cluster_off')))
        return
    if snapshot.cluster_note == 'redis':
        print(format_console('warning', t('celery_balance_cluster_redis_down')))
    print(
        t(
            'celery_balance_cluster_header',
            role=snapshot.settings.cluster_role,
            node=snapshot.settings.node_id,
        )
    )
    if not snapshot.cluster_nodes:
        print(t('celery_balance_cluster_empty'))
        return
    plans = {
        item.node_id: item
        for item in snapshot.cluster_plans
        if hasattr(item, 'node_id')
    }
    for node in snapshot.cluster_nodes:
        plan = plans.get(node.node_id)
        queues = ', '.join(plan.queues) if plan and plan.queues else '-'
        if node.gpu_available:
            gpu = t(
                'celery_balance_gpu_yes',
                count=1,
                free=f'{node.vram_free_mb:.0f}',
                total=f'{node.vram_total_mb:.0f}',
            )
        else:
            gpu = t('celery_balance_gpu_no')
        print(
            t(
                'celery_balance_cluster_node_line',
                node=node.node_id,
                role=t('celery_balance_cluster_primary') if node.primary else t('celery_balance_cluster_worker'),
                ram=f'{node.celery_ram_budget_mb:.0f}',
                cpu=f'{node.celery_cpu_budget:g}',
                gpu=gpu,
                queues=queues,
            )
        )
    if snapshot.quarantine:
        print(t('celery_balance_quarantine_header'))
        for row in snapshot.quarantine:
            print(
                t(
                    'celery_balance_quarantine_line',
                    queue=row.get('queue') or '',
                    reason=row.get('reason') or '-',
                    node=row.get('node_id') or '-',
                    ts=row.get('ts') or '-',
                )
            )
    else:
        print(t('celery_balance_quarantine_empty'))
