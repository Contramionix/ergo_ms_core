"""Деление потолков очередей между живыми узлами.

Одна задача по-прежнему исполняется целиком на одном узле. Здесь только
доля одновременных слотов: сумма по узлам не выше max_parallel очереди.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from celery_balance.apply import should_skip_change
from celery_balance.constants import (
    AUTO_PLACEMENT_AGENT,
    CLASS_HEAVY,
    CLASS_LIGHT,
    DEFAULT_PREFETCH,
    HEAVY_PREFETCH,
    PLACEMENT_AGENT,
    PLACEMENT_ANY,
    PLACEMENT_AUTO,
    PLACEMENT_GPU,
    PLACEMENT_PRIMARY,
)
from celery_balance.footprint_loader import FootprintCatalog, TaskFootprint, resolve_footprint
from celery_balance.history import HistoryStats
from celery_balance.planner import WorkerPlan, _effective_footprint
from celery_balance.settings import BalanceSettings


@dataclass(frozen=True)
class NodeView:
    node_id: str
    primary: bool
    celery_ram_budget_mb: float
    celery_cpu_budget: float
    cpu_count: float
    gpu_available: bool
    vram_free_mb: float
    utilization_pct: float
    devices: tuple[tuple[int, float], ...] = ()
    vram_total_mb: float = 0.0
    egress_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            'node_id': self.node_id,
            'primary': self.primary,
            'celery_ram_budget_mb': self.celery_ram_budget_mb,
            'celery_cpu_budget': self.celery_cpu_budget,
            'cpu_count': self.cpu_count,
            'gpu_available': self.gpu_available,
            'vram_free_mb': self.vram_free_mb,
            'utilization_pct': self.utilization_pct,
            'egress_ok': self.egress_ok,
        }


@dataclass
class NodePlan:
    node_id: str
    primary: bool
    queues: list[str]
    concurrency: int
    prefetch_multiplier: int
    queue_limits: dict[str, int]
    queue_classes: dict[str, str]
    pause_queues: list[str]
    reasons: list[str] = field(default_factory=list)

    def to_overlay(self) -> dict[str, Any]:
        return {
            'version': 1,
            'node_id': self.node_id,
            'allowed_queues': list(self.queues),
            'queue_limits': dict(self.queue_limits),
            'queue_classes': dict(self.queue_classes),
            'pause_queues': list(self.pause_queues),
            'reserve_light': 0,
            'non_light_cap': self.concurrency,
            'plans': {
                'cluster': {
                    'name': 'cluster',
                    'hostname': self.node_id,
                    'queues': list(self.queues),
                    'concurrency': self.concurrency,
                    'prefetch_multiplier': self.prefetch_multiplier,
                    'queue_limits': dict(self.queue_limits),
                    'queue_classes': dict(self.queue_classes),
                    'pause_queues': list(self.pause_queues),
                    'non_light_cap': self.concurrency,
                    'reserve_light': 0,
                }
            },
        }


def _capacity(node: NodeView, spec: TaskFootprint) -> int:
    ram_slots = math.floor(node.celery_ram_budget_mb / spec.ram_mb) if spec.ram_mb > 0 else 1
    cpu_slots = math.floor(node.celery_cpu_budget / spec.cpu_units) if spec.cpu_units > 0 else 1
    slots = max(0, min(ram_slots, cpu_slots))
    if not spec.gpu_required and spec.placement != PLACEMENT_GPU:
        return slots
    if spec.vram_mb <= 0:
        gpu_slots = 1 if node.gpu_available else 0
    elif node.devices:
        gpu_slots = sum(math.floor(free / spec.vram_mb) for _, free in node.devices if free > 0)
    elif node.gpu_available and node.vram_free_mb > 0:
        gpu_slots = math.floor(node.vram_free_mb / spec.vram_mb)
    else:
        gpu_slots = 0
    if spec.placement == PLACEMENT_GPU or spec.gpu_required:
        if node.gpu_available:
            return min(slots, gpu_slots)
        if spec.cpu_fallback and spec.placement != PLACEMENT_GPU:
            return slots
        return 0
    return slots


def _eligible(spec: TaskFootprint, nodes: list[NodeView]) -> list[NodeView]:
    primary = [node for node in nodes if node.primary]
    if spec.placement == PLACEMENT_PRIMARY:
        return primary or nodes[:1]
    if spec.placement == PLACEMENT_GPU:
        gpu_nodes = [node for node in nodes if node.gpu_available and _capacity(node, spec) > 0]
        if gpu_nodes:
            return gpu_nodes
        if spec.cpu_fallback:
            return primary or nodes[:1]
        return []
    fitted = [node for node in nodes if _capacity(node, spec) > 0]
    if fitted:
        return fitted
    return primary or nodes[:1]


def _split(total: int, weights: list[int]) -> list[int]:
    if not weights:
        return []
    capped = [max(0, int(weight)) for weight in weights]
    budget = min(max(0, int(total)), sum(capped))
    if budget <= 0 or sum(capped) <= 0:
        return [0 for _ in capped]
    # Иначе большая машина забирает единственные слоты, и маленький узел простаивает.
    reserved = [0 for _ in capped]
    positive = [index for index, weight in enumerate(capped) if weight > 0]
    if positive and budget >= len(positive):
        for index in positive:
            reserved[index] = 1
            capped[index] -= 1
        budget -= len(positive)
    if budget <= 0 or sum(capped) <= 0:
        return reserved
    raw = [budget * weight / sum(capped) for weight in capped]
    floors = [min(capped[index], math.floor(raw[index])) for index in range(len(capped))]
    leftover = budget - sum(floors)
    order = sorted(
        range(len(capped)),
        key=lambda index: (raw[index] - math.floor(raw[index]), capped[index]),
        reverse=True,
    )
    for index in order:
        if leftover <= 0:
            break
        if floors[index] >= capped[index]:
            continue
        floors[index] += 1
        leftover -= 1
    return [reserved[index] + floors[index] for index in range(len(floors))]


def _agent_share(
    spec: TaskFootprint,
    nodes: list[NodeView],
) -> tuple[list[NodeView], list[int], list[NodeView]]:
    """Пока жив рабочий узел, очередь слушает только он. Сверх его бюджета задачи ждут в брокере.

    Третий список — узлы, которым очередь не отдана, потому что нет выхода в сеть.
    """
    primary = [node for node in nodes if node.primary]
    agents: list[NodeView] = []
    blocked: list[NodeView] = []
    for node in nodes:
        if node.primary:
            continue
        if spec.needs_network and not node.egress_ok:
            blocked.append(node)
            continue
        if _capacity(node, spec) > 0:
            agents.append(node)
    if not agents:
        eligible = primary or nodes[:1]
        weights = [_capacity(node, spec) for node in eligible]
        return eligible, _split(spec.max_parallel, weights), blocked
    agent_slots = _split(spec.max_parallel, [_capacity(node, spec) for node in agents])
    if sum(agent_slots) > 0:
        # Общая очередь: если менеджер тоже слушает, он забирает сообщения раньше узла.
        return agents, agent_slots, blocked
    eligible = primary or nodes[:1]
    weights = [_capacity(node, spec) for node in eligible]
    return eligible, _split(spec.max_parallel, weights), blocked


def _resolve_auto(
    spec: TaskFootprint,
    settings: BalanceSettings,
    quarantined: set[str],
) -> TaskFootprint:
    """auto: процессорные medium и heavy уходят на рабочие узлы, пока очередь не в карантине."""
    if spec.placement != PLACEMENT_AUTO:
        return spec
    movable = (
        settings.auto_placement == AUTO_PLACEMENT_AGENT
        and spec.task_class != CLASS_LIGHT
        and not spec.gpu_required
        and spec.queue not in quarantined
    )
    if movable:
        return replace(spec, placement=PLACEMENT_AGENT, needs_network=True)
    return replace(spec, placement=PLACEMENT_PRIMARY)


def plan_cluster(
    nodes: list[NodeView],
    *,
    all_queues: list[str],
    catalog: FootprintCatalog,
    settings: BalanceSettings,
    depths: dict[str, int],
    history: dict[str, HistoryStats],
    previous_limits: dict[str, dict[str, int]] | None = None,
    agent_ready: bool = True,
    quarantined: set[str] | None = None,
) -> list[NodePlan]:
    """Доли очередей. Узлы, которых нет в списке, уже отсеяны по TTL."""
    if not nodes:
        return []
    previous_limits = previous_limits or {}
    shares: dict[str, dict[str, int]] = {node.node_id: {} for node in nodes}
    classes: dict[str, str] = {}
    paused: dict[str, list[str]] = {node.node_id: [] for node in nodes}
    reasons: dict[str, list[str]] = {node.node_id: [] for node in nodes}
    held_on_primary: set[str] = set()

    for queue in all_queues:
        spec = _effective_footprint(resolve_footprint(queue, catalog), history)
        spec = _resolve_auto(spec, settings, quarantined or set())
        if spec.placement == PLACEMENT_AGENT and not agent_ready:
            spec = replace(spec, placement=PLACEMENT_PRIMARY)
        classes[queue] = spec.task_class
        blocked: list[NodeView] = []
        if spec.placement == PLACEMENT_AGENT:
            eligible, split, blocked = _agent_share(spec, nodes)
            weights = []
            for node, slots in zip(eligible, split):
                if node.primary and slots > 0 and any(not item.primary for item in eligible):
                    weights.append(slots)
                else:
                    weights.append(_capacity(node, spec))
        else:
            eligible = _eligible(spec, nodes)
            weights = [_capacity(node, spec) for node in eligible]
            split = _split(spec.max_parallel, weights)
        for node in blocked:
            reasons[node.node_id].append(f'{queue}: нет выхода в сеть')
        if not eligible:
            holder = next((node for node in nodes if node.primary), nodes[0])
            paused[holder.node_id].append(queue)
            reasons[holder.node_id].append(f'{queue}: нет узла под placement={spec.placement}')
            continue
        prev_by_node = {
            node.node_id: int((previous_limits.get(node.node_id) or {}).get(queue, -1))
            for node in eligible
        }
        fresh_sum = sum(split)
        kept = []
        for node, slots, weight in zip(eligible, split, weights):
            previous = prev_by_node[node.node_id]
            if previous >= 0 and should_skip_change(previous, slots, settings.hysteresis_ratio):
                slots = min(previous, weight)
            kept.append(min(slots, weight))
        if sum(kept) > spec.max_parallel or sum(kept) > fresh_sum:
            kept = split
        for node, slots in zip(eligible, kept):
            if slots > 0:
                shares[node.node_id][queue] = slots
            reasons[node.node_id].append(f'{queue}: {slots}/{spec.max_parallel}')
        for node in nodes:
            if node not in eligible:
                reasons[node.node_id].append(f'{queue}: placement={spec.placement}')
        holder = next((node for node in nodes if node.primary), None)
        if holder is not None:
            elsewhere = sum(
                shares[node.node_id].get(queue, 0)
                for node in nodes
                if not node.primary
            )
            primary_slots = shares[holder.node_id].get(queue, 0)
            if elsewhere > 0 and primary_slots <= 0:
                if spec.placement != PLACEMENT_GPU:
                    held_on_primary.add(queue)
                if queue not in paused[holder.node_id]:
                    paused[holder.node_id].append(queue)

    plans: list[NodePlan] = []
    for node in nodes:
        limits = shares[node.node_id]
        allowed = sorted(limits)
        if node.primary:
            allowed = sorted(set(allowed) | held_on_primary)
        hard = settings.max_concurrency or max(1, int(math.floor(node.cpu_count * 2)))
        concurrency = min(hard, sum(limits.values())) if limits else 0
        heavy = any(classes.get(name) == CLASS_HEAVY for name in allowed)
        plans.append(
            NodePlan(
                node_id=node.node_id,
                primary=node.primary,
                queues=allowed,
                concurrency=concurrency,
                prefetch_multiplier=HEAVY_PREFETCH if heavy else DEFAULT_PREFETCH,
                queue_limits=dict(limits),
                queue_classes={name: classes[name] for name in allowed if name in classes},
                pause_queues=list(paused[node.node_id]),
                reasons=reasons[node.node_id],
            )
        )
    return plans


def apply_cluster_share(plans: list[WorkerPlan], node_plan: NodePlan) -> None:
    """Потолок очереди на этом узле — минимум локального плана и доли кластера."""
    allowed = set(node_plan.queues)
    for plan in plans:
        for queue in list(plan.queue_limits):
            if queue not in allowed:
                plan.queue_limits[queue] = 0
                if queue not in plan.pause_queues:
                    plan.pause_queues.append(queue)
                continue
            share = node_plan.queue_limits.get(queue, 0)
            if share <= 0:
                plan.queue_limits[queue] = 0
                if queue not in plan.pause_queues:
                    plan.pause_queues.append(queue)
                continue
            current = plan.queue_limits.get(queue, share)
            plan.queue_limits[queue] = min(current, share) if current > 0 else share
        plan.reasons.append(f'cluster node {node_plan.node_id}')
