"""Сборка снимка и плана балансировщика."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from celery_balance.footprint_loader import load_footprints
from celery_balance.forecast import Forecast, build_forecast
from celery_balance.history import stats_by_queue
from celery_balance.host_budget import HostBudget, sample_budget
from celery_balance.overlay import load_decision, write_decision
from celery_balance.planner import WorkerPlan, plan_all
from celery_balance.queues import QueuesReport, load_queue_names, observe_queues
from celery_balance.settings import BalanceSettings, load_settings
from celery_balance.workers import WorkersFile, load_workers_file, resolve_worker_queues


@dataclass
class BalanceSnapshot:
    settings: BalanceSettings
    budget: HostBudget
    queues: QueuesReport
    workers_file: WorkersFile
    plans: list[WorkerPlan]
    forecast: Forecast
    overlay_path: Path | None
    cluster_nodes: list[Any] = field(default_factory=list)
    cluster_plans: list[Any] = field(default_factory=list)
    cluster_note: str = ''
    allowed_queues: list[str] | None = None
    quarantine: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'mode': self.settings.mode,
            'budget': self.budget.to_dict(),
            'queues': self.queues.to_dict(),
            'workers_yaml': self.workers_file.to_dict(),
            'forecast': self.forecast.to_dict(),
            'plans': [item.to_dict() for item in self.plans],
            'overlay_path': str(self.overlay_path) if self.overlay_path else None,
            'cluster_note': self.cluster_note,
            'quarantine': list(self.quarantine),
            'allowed_queues': self.allowed_queues,
            'cluster_nodes': [
                item.to_dict() if hasattr(item, 'to_dict') else item
                for item in self.cluster_nodes
            ],
            'cluster_plans': [
                item.to_overlay() if hasattr(item, 'to_overlay') else item
                for item in self.cluster_plans
            ],
        }


def extra_queue_names(workers_file: WorkersFile, cached: list[str]) -> list[str]:
    names: set[str] = set()
    for worker in workers_file.workers:
        names.update(resolve_worker_queues(worker.queues, cached))
    return sorted(names)


def collect_snapshot(project_root: Path) -> BalanceSnapshot:
    settings = load_settings(project_root)
    budget = sample_budget(project_root, settings)
    if settings.egress_url:
        from celery_balance.egress import probe_egress

        budget = replace(budget, egress_ok=probe_egress(settings.egress_url))
    workers_file = load_workers_file(project_root)
    cached = load_queue_names(project_root)
    extras = extra_queue_names(workers_file, cached)
    queues = observe_queues(project_root, extras)
    catalog = load_footprints(str(project_root.resolve()))
    history = stats_by_queue(project_root)
    forecast = build_forecast(queues.queues, history, project_root)
    plans = plan_all(
        workers_file.workers,
        all_queues=cached,
        catalog=catalog,
        budget=budget,
        settings=settings,
        queue_snapshots=queues.queues,
        history=history,
        pending_sec=forecast.pending_sec,
        previous=previous_concurrency(project_root),
    )
    return BalanceSnapshot(
        settings=settings,
        budget=budget,
        queues=queues,
        workers_file=workers_file,
        plans=plans,
        forecast=forecast,
        overlay_path=None,
    )


def persist_snapshot(project_root: Path, snapshot: BalanceSnapshot) -> Path:
    path = write_decision(
        project_root,
        settings=snapshot.settings,
        budget=snapshot.budget.to_dict(),
        queues=snapshot.queues.to_dict(),
        forecast=snapshot.forecast.to_dict(),
        workers=snapshot.plans,
        yaml_workers=snapshot.workers_file.to_dict(),
        allowed_queues=snapshot.allowed_queues,
        node_id=snapshot.settings.node_id if snapshot.settings.cluster_enabled else None,
    )
    snapshot.overlay_path = path
    return path


def previous_concurrency(project_root: Path) -> dict[str, int]:
    data = load_decision(project_root)
    if not data:
        return {}
    plans = data.get('plans')
    if not isinstance(plans, dict):
        return {}
    result: dict[str, int] = {}
    for name, raw in plans.items():
        if not isinstance(raw, dict):
            continue
        try:
            result[str(name)] = int(raw.get('concurrency'))
        except (TypeError, ValueError):
            continue
    return result
