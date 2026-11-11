"""Бюджет и план узла в Redis. Ключи живут, пока узел присылает бюджет."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from celery_balance.constants import (
    LAST_PLAN_FILENAME,
    NODE_KEY_PREFIX,
    PLAN_KEY_PREFIX,
    QUARANTINE_KEY_PREFIX,
    ROLE_AGENT,
    ROLE_MANAGER,
)
from celery_balance.cluster_plan import NodePlan, NodeView, apply_cluster_share, plan_cluster
from celery_balance.host_budget import HostBudget
from celery_balance.overlay import load_decision
from celery_balance.settings import BalanceSettings, load_settings
from project_layout import cache_celery_balance_dir, ensure_dir


def _node_key(node_id: str) -> str:
    return f'{NODE_KEY_PREFIX}{node_id}'


def _plan_key(node_id: str) -> str:
    return f'{PLAN_KEY_PREFIX}{node_id}'


def connect(project_root: Path) -> Any | None:
    from env_file_loader import load_project_env

    from celery_balance.queues import _redis_connect_kwargs

    try:
        import redis
    except ImportError:
        return None
    kwargs = _redis_connect_kwargs(project_root, load_project_env(project_root))
    try:
        client = redis.Redis(decode_responses=True, **kwargs)
        client.ping()
    except Exception:  # noqa: BLE001 — нет брокера, кластер молча остаётся локальным
        return None
    return client


def view_from_budget(node_id: str, primary: bool, budget: HostBudget) -> NodeView:
    devices = tuple((item.index, item.vram_free_mb) for item in budget.gpu.devices)
    return NodeView(
        node_id=node_id,
        primary=primary,
        celery_ram_budget_mb=budget.celery_ram_budget_mb,
        celery_cpu_budget=budget.celery_cpu_budget,
        cpu_count=budget.cpu_count,
        gpu_available=budget.gpu.available,
        vram_free_mb=budget.gpu.vram_free_mb,
        utilization_pct=budget.gpu.utilization_pct,
        devices=devices,
        vram_total_mb=budget.gpu.vram_total_mb,
        egress_ok=budget.egress_ok,
    )


def view_from_payload(data: dict[str, Any]) -> NodeView | None:
    node_id = str(data.get('node_id') or '').strip()
    budget = data.get('budget')
    if not node_id or not isinstance(budget, dict):
        return None
    gpu = budget.get('gpu') if isinstance(budget.get('gpu'), dict) else {}
    devices: list[tuple[int, float]] = []
    raw_devices = gpu.get('devices') if isinstance(gpu, dict) else None
    if isinstance(raw_devices, list):
        for item in raw_devices:
            if not isinstance(item, dict):
                continue
            try:
                devices.append((int(item.get('index') or 0), float(item.get('vram_free_mb') or 0)))
            except (TypeError, ValueError):
                continue
    try:
        return NodeView(
            node_id=node_id,
            primary=bool(data.get('primary')),
            celery_ram_budget_mb=float(budget.get('celery_ram_budget_mb') or 0),
            celery_cpu_budget=float(budget.get('celery_cpu_budget') or 0),
            cpu_count=float(budget.get('cpu_count') or 1),
            gpu_available=bool(gpu.get('available')) if isinstance(gpu, dict) else False,
            vram_free_mb=float(gpu.get('vram_free_mb') or 0) if isinstance(gpu, dict) else 0.0,
            utilization_pct=float(gpu.get('utilization_pct') or 0) if isinstance(gpu, dict) else 0.0,
            devices=tuple(devices),
            vram_total_mb=float(gpu.get('vram_total_mb') or 0) if isinstance(gpu, dict) else 0.0,
            egress_ok=bool(budget.get('egress_ok', True)),
        )
    except (TypeError, ValueError):
        return None


def publish_node(client: Any, settings: BalanceSettings, budget: HostBudget) -> None:
    payload = {
        'node_id': settings.node_id,
        'role': settings.cluster_role,
        'primary': settings.cluster_role == ROLE_MANAGER,
        'budget': budget.to_dict(),
    }
    client.set(_node_key(settings.node_id), json.dumps(payload, ensure_ascii=False), ex=settings.node_ttl_sec)


def list_views(client: Any) -> list[NodeView]:
    try:
        keys = list(client.scan_iter(match=f'{NODE_KEY_PREFIX}*'))
    except Exception:  # noqa: BLE001
        return []
    if not keys:
        return []
    try:
        raw_values = client.mget(keys)
    except Exception:  # noqa: BLE001
        return []
    views: list[NodeView] = []
    for raw in raw_values:
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        view = view_from_payload(data)
        if view is not None:
            views.append(view)
    return views


def _quarantine_key(queue: str) -> str:
    return f'{QUARANTINE_KEY_PREFIX}{queue}'


def list_quarantine(client: Any) -> list[dict[str, Any]]:
    """Очереди, которые рабочий узел вернул на основной сервер."""
    try:
        keys = list(client.scan_iter(match=f'{QUARANTINE_KEY_PREFIX}*'))
    except Exception:  # noqa: BLE001
        return []
    if not keys:
        return []
    try:
        raw_values = client.mget(keys)
    except Exception:  # noqa: BLE001
        return []
    rows: list[dict[str, Any]] = []
    for key, raw in zip(keys, raw_values):
        queue = str(key)[len(QUARANTINE_KEY_PREFIX):]
        if not queue:
            continue
        row = {'queue': queue, 'reason': '', 'node_id': '', 'ts': ''}
        if raw:
            try:
                data = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                data = None
            if isinstance(data, dict):
                row['reason'] = str(data.get('reason') or '')
                row['node_id'] = str(data.get('node_id') or '')
                row['ts'] = str(data.get('ts') or '')
        rows.append(row)
    return sorted(rows, key=lambda item: item['queue'])


def release_quarantine(client: Any, queue: str | None) -> int:
    """Снимает одну очередь или все. Возвращает число удалённых ключей."""
    if queue:
        try:
            return int(client.delete(_quarantine_key(queue)) or 0)
        except Exception:  # noqa: BLE001
            return 0
    try:
        keys = list(client.scan_iter(match=f'{QUARANTINE_KEY_PREFIX}*'))
    except Exception:  # noqa: BLE001
        return 0
    if not keys:
        return 0
    try:
        return int(client.delete(*keys) or 0)
    except Exception:  # noqa: BLE001
        return 0


def publish_plan(client: Any, plan: NodePlan, ttl_sec: int) -> None:
    client.set(
        _plan_key(plan.node_id),
        json.dumps(plan.to_overlay(), ensure_ascii=False),
        ex=ttl_sec,
    )


def renew_plans(client: Any, ttl_sec: int) -> int:
    """Продлить TTL уже опубликованных планов без пересчёта. Число обновлённых ключей."""
    if ttl_sec < 1:
        return 0
    try:
        keys = list(client.scan_iter(match=f'{PLAN_KEY_PREFIX}*'))
    except Exception:  # noqa: BLE001
        return 0
    renewed = 0
    for key in keys:
        try:
            if client.expire(key, ttl_sec):
                renewed += 1
        except Exception:  # noqa: BLE001
            continue
    return renewed


def load_plan(client: Any, node_id: str) -> dict[str, Any] | None:
    try:
        raw = client.get(_plan_key(node_id))
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _last_plan_path(project_root: Path) -> Path:
    return cache_celery_balance_dir(project_root) / LAST_PLAN_FILENAME


def save_last_plan(project_root: Path, plan: dict[str, Any], *, node_id: str) -> None:
    """Кэш последнего живого плана агента: переживает краткое протухание ключа в Redis."""
    previous = load_last_plan(project_root, node_id=node_id) or {}
    payload = {
        'node_id': node_id,
        'allowed_queues': (
            list(plan['allowed_queues'])
            if isinstance(plan.get('allowed_queues'), list)
            else list(previous.get('allowed_queues') or [])
        ),
        'pause_queues': (
            list(plan['pause_queues'])
            if isinstance(plan.get('pause_queues'), list)
            else list(previous.get('pause_queues') or [])
        ),
        'queue_limits': (
            dict(plan['queue_limits'])
            if isinstance(plan.get('queue_limits'), dict)
            else dict(previous.get('queue_limits') or {})
        ),
    }
    path = _last_plan_path(project_root)
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load_last_plan(project_root: Path, *, node_id: str) -> dict[str, Any] | None:
    path = _last_plan_path(project_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if str(data.get('node_id') or '') != node_id:
        return None
    return data


def _limits_from_plan(data: dict[str, Any] | None) -> dict[str, int]:
    if not data:
        return {}
    raw = data.get('queue_limits')
    if not isinstance(raw, dict):
        return {}
    limits: dict[str, int] = {}
    for name, value in raw.items():
        try:
            limits[str(name)] = int(value)
        except (TypeError, ValueError):
            continue
    return limits


def _merge_nodes(local: NodeView, remote: list[NodeView]) -> list[NodeView]:
    by_id = {item.node_id: item for item in remote}
    by_id[local.node_id] = local
    return sorted(by_id.values(), key=lambda item: (not item.primary, item.node_id))


def _agent_image_ready(project_root: Path) -> bool:
    """Маркер пишет старт, когда образ воркера уже умеет готовить пакеты на узле."""
    from project_layout import cache_dir

    return (cache_dir(project_root) / 'celery_balance' / 'agent_ready').is_file()


def sync_cluster(project_root: Path, snapshot: Any, *, write: bool) -> None:
    """Менеджер делит очереди. Агент только публикует свой бюджет."""
    settings = snapshot.settings
    if not settings.cluster_enabled:
        return
    local = view_from_budget(
        settings.node_id,
        settings.cluster_role == ROLE_MANAGER,
        snapshot.budget,
    )
    client = connect(project_root)
    remote: list[NodeView] = []
    previous: dict[str, dict[str, int]] = {}
    quarantine_rows: list[dict[str, Any]] = []
    if client is None:
        snapshot.cluster_note = 'redis'
    else:
        if write:
            publish_node(client, settings, snapshot.budget)
        remote = list_views(client)
        quarantine_rows = list_quarantine(client)
        for view in _merge_nodes(local, remote):
            previous[view.node_id] = _limits_from_plan(load_plan(client, view.node_id))
    nodes = _merge_nodes(local, remote)
    snapshot.cluster_nodes = nodes
    snapshot.quarantine = quarantine_rows
    if settings.cluster_role != ROLE_MANAGER:
        return

    depths = {
        item.name: int(item.depth or 0)
        for item in snapshot.queues.queues
        if item.depth is not None
    }
    queue_names = sorted({item.name for item in snapshot.queues.queues} | set(depths))
    if not queue_names:
        queue_names = ['default']
    from celery_balance.history import stats_by_queue
    from celery_balance.workers import declared_module_queues

    catalog = _catalog(project_root)
    queue_names = sorted(
        set(queue_names)
        | declared_module_queues(project_root)
        | {item.queue for item in catalog.tasks}
    )

    plans = plan_cluster(
        nodes,
        all_queues=queue_names,
        catalog=catalog,
        settings=settings,
        depths=depths,
        history=stats_by_queue(project_root),
        previous_limits=previous,
        agent_ready=_agent_image_ready(project_root),
        quarantined={str(item.get('queue') or '') for item in quarantine_rows},
    )
    snapshot.cluster_plans = plans
    local_plan = next((item for item in plans if item.node_id == settings.node_id), None)
    if local_plan is not None:
        apply_cluster_share(snapshot.plans, local_plan)
        snapshot.allowed_queues = list(local_plan.queues)
    if write and client is not None:
        for plan in plans:
            publish_plan(client, plan, settings.plan_ttl_sec)


def _catalog(project_root: Path):
    from celery_balance.footprint_loader import load_footprints

    return load_footprints(str(project_root.resolve()))


def _plan_from_decision(project_root: Path, node_id: str, field: str) -> dict[str, Any] | None:
    data = load_decision(project_root)
    if (
        isinstance(data, dict)
        and data.get('node_id') == node_id
        and field in data
    ):
        return data
    return None


def resolve_allowed_queues(project_root: Path) -> list[str] | None:
    """None — фильтр кластера не действует. Пустой список — воркер не стартует."""
    settings = load_settings(project_root)
    if not settings.cluster_enabled:
        return None
    plan: dict[str, Any] | None = None
    from_redis = False
    client = connect(project_root)
    if client is not None:
        plan = load_plan(client, settings.node_id)
        if plan is not None and 'allowed_queues' in plan:
            from_redis = True
            save_last_plan(project_root, plan, node_id=settings.node_id)
    if plan is None or 'allowed_queues' not in plan:
        # Ключа нет — краткий сбой TTL. Живой Redis с пустым списком уважаем выше.
        cached = load_last_plan(project_root, node_id=settings.node_id)
        if cached is not None and 'allowed_queues' in cached:
            plan = cached
    if plan is None or 'allowed_queues' not in plan:
        plan = _plan_from_decision(project_root, settings.node_id, 'allowed_queues')
    if plan is None or 'allowed_queues' not in plan:
        if settings.cluster_role == ROLE_AGENT:
            return []
        return None
    raw = plan.get('allowed_queues')
    if not isinstance(raw, list):
        return [] if settings.cluster_role == ROLE_AGENT else None
    queues = [str(item) for item in raw if str(item).strip()]
    if from_redis and not queues and settings.cluster_role == ROLE_AGENT:
        # Менеджер явно не дал очереди — кэш не подменяет.
        return []
    return queues


def resolve_paused_queues(project_root: Path) -> list[str] | None:
    """None — кластер выключен и пауза не действует. Иначе очереди, которые этот узел не слушает."""
    settings = load_settings(project_root)
    if not settings.cluster_enabled:
        return None
    plan: dict[str, Any] | None = None
    client = connect(project_root)
    if client is not None:
        plan = load_plan(client, settings.node_id)
        if plan is not None and 'pause_queues' in plan:
            save_last_plan(project_root, plan, node_id=settings.node_id)
    if plan is None or 'pause_queues' not in plan:
        cached = load_last_plan(project_root, node_id=settings.node_id)
        if cached is not None and 'pause_queues' in cached:
            plan = cached
    if plan is None or 'pause_queues' not in plan:
        plan = _plan_from_decision(project_root, settings.node_id, 'pause_queues')
    if plan is None or 'pause_queues' not in plan:
        return []
    raw = plan.get('pause_queues')
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]
