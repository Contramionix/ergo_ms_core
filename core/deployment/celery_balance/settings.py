"""Режим и knobs балансировщика из env (без записи в .env)."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path

from env_file_loader import load_project_env

from celery_balance.constants import (
    CLUSTER_MODES,
    CLUSTER_OFF,
    CLUSTER_ON,
    CLUSTER_ROLES,
    AUTO_PLACEMENT_OFF,
    AUTO_PLACEMENTS,
    DEFAULT_AUTO_PLACEMENT,
    DEFAULT_CLUSTER,
    DEFAULT_CLUSTER_ROLE,
    DEFAULT_GPU_UTIL_CAP,
    DEFAULT_QUARANTINE_TTL_SEC,
    DEFAULT_HYSTERESIS_RATIO,
    DEFAULT_MIN_CONCURRENCY,
    DEFAULT_NODE_TTL_SEC,
    DEFAULT_OS_RESERVE_RAM_MB,
    DEFAULT_PLAN_TTL_MIN_SEC,
    DEFAULT_PLAN_TTL_SEC,
    DEFAULT_RESERVE_CPU,
    DEFAULT_MODE,
    DEFAULT_WATCH_INTERVAL_SEC,
    MODE_AUTO,
    MODE_OFF,
    MODE_RECOMMEND,
    MODES,
    ROLE_MANAGER,
)


def _pick(environ: dict[str, str], key: str, default: str = '') -> str:
    raw = os.environ.get(key)
    if raw is not None and str(raw).strip() != '':
        return str(raw).strip()
    value = environ.get(key, default)
    return str(value).strip() if value is not None else default


def _as_int(raw: str, default: int | None) -> int | None:
    text = (raw or '').strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


def _as_float(raw: str, default: float) -> float:
    text = (raw or '').strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


@dataclass(frozen=True)
class BalanceSettings:
    mode: str
    os_reserve_ram_mb: int
    reserve_cpu: float
    min_concurrency: int
    max_concurrency: int | None
    gpu_enabled: bool
    gpu_util_cap: float
    watch_interval_sec: float
    hysteresis_ratio: float
    cluster: str
    cluster_role: str
    node_id: str
    node_ttl_sec: int
    plan_ttl_sec: int = DEFAULT_PLAN_TTL_SEC
    egress_url: str = ''
    auto_placement: str = DEFAULT_AUTO_PLACEMENT
    quarantine_ttl_sec: int = DEFAULT_QUARANTINE_TTL_SEC

    @property
    def apply_overlay(self) -> bool:
        return self.mode == MODE_AUTO

    @property
    def cluster_enabled(self) -> bool:
        return self.cluster == CLUSTER_ON

    @property
    def compute_plan(self) -> bool:
        return self.mode in {MODE_RECOMMEND, MODE_AUTO}


def load_settings(project_root: Path) -> BalanceSettings:
    environ = load_project_env(project_root)
    mode = _pick(environ, 'CELERY_BALANCE', DEFAULT_MODE).lower()
    if mode in {'advise', 'disabled', 'false', '0', 'no'}:
        mode = MODE_OFF
    if mode not in MODES:
        mode = DEFAULT_MODE

    gpu_raw = _pick(environ, 'CELERY_BALANCE_GPU', 'auto').lower()
    gpu_enabled = gpu_raw not in {'off', 'false', '0', 'no'}

    max_conc = _as_int(_pick(environ, 'CELERY_BALANCE_MAX_CONCURRENCY'), None)
    if max_conc is not None and max_conc < 1:
        max_conc = 1

    min_conc = _as_int(
        _pick(environ, 'CELERY_BALANCE_MIN_CONCURRENCY'),
        DEFAULT_MIN_CONCURRENCY,
    )
    if min_conc is None or min_conc < 1:
        min_conc = DEFAULT_MIN_CONCURRENCY

    os_reserve = _as_int(
        _pick(environ, 'CELERY_BALANCE_OS_RESERVE_RAM_MB'),
        DEFAULT_OS_RESERVE_RAM_MB,
    )
    if os_reserve is None or os_reserve < 0:
        os_reserve = DEFAULT_OS_RESERVE_RAM_MB

    cluster = _pick(environ, 'CELERY_CLUSTER', DEFAULT_CLUSTER).lower()
    if cluster in {'1', 'true', 'yes', 'on'}:
        cluster = CLUSTER_ON
    if cluster not in CLUSTER_MODES:
        cluster = CLUSTER_OFF

    role = _pick(environ, 'CELERY_CLUSTER_ROLE', DEFAULT_CLUSTER_ROLE).lower()
    if role not in CLUSTER_ROLES:
        role = ROLE_MANAGER

    node_id = _pick(environ, 'ERGO_NODE_ID', '') or socket.gethostname()
    node_ttl = _as_int(_pick(environ, 'CELERY_CLUSTER_NODE_TTL'), DEFAULT_NODE_TTL_SEC)
    if node_ttl is None or node_ttl < 15:
        node_ttl = DEFAULT_NODE_TTL_SEC

    watch_interval = max(
        5.0,
        _as_float(
            _pick(environ, 'CELERY_BALANCE_WATCH_INTERVAL'),
            DEFAULT_WATCH_INTERVAL_SEC,
        ),
    )
    plan_ttl_raw = _as_int(_pick(environ, 'CELERY_CLUSTER_PLAN_TTL'), None)
    if plan_ttl_raw is not None and plan_ttl_raw >= DEFAULT_PLAN_TTL_MIN_SEC:
        plan_ttl = plan_ttl_raw
    else:
        plan_ttl = max(
            DEFAULT_PLAN_TTL_SEC,
            node_ttl * 2,
            int(watch_interval * 6),
        )

    auto_placement = _pick(environ, 'CELERY_CLUSTER_AUTO_PLACEMENT', DEFAULT_AUTO_PLACEMENT).lower()
    if auto_placement in {'0', 'false', 'no', 'primary'}:
        auto_placement = AUTO_PLACEMENT_OFF
    if auto_placement not in AUTO_PLACEMENTS:
        auto_placement = DEFAULT_AUTO_PLACEMENT

    quarantine_ttl = _as_int(
        _pick(environ, 'CELERY_CLUSTER_QUARANTINE_TTL'),
        DEFAULT_QUARANTINE_TTL_SEC,
    )
    if quarantine_ttl is None or quarantine_ttl < 60:
        quarantine_ttl = DEFAULT_QUARANTINE_TTL_SEC

    return BalanceSettings(
        mode=mode,
        os_reserve_ram_mb=os_reserve,
        reserve_cpu=max(
            0.0,
            _as_float(_pick(environ, 'CELERY_BALANCE_RESERVE_CPU'), DEFAULT_RESERVE_CPU),
        ),
        min_concurrency=min_conc,
        max_concurrency=max_conc,
        gpu_enabled=gpu_enabled,
        gpu_util_cap=max(
            0.0,
            min(
                100.0,
                _as_float(
                    _pick(environ, 'CELERY_BALANCE_GPU_UTIL_CAP'),
                    DEFAULT_GPU_UTIL_CAP,
                ),
            ),
        ),
        watch_interval_sec=watch_interval,
        hysteresis_ratio=max(
            0.0,
            _as_float(
                _pick(environ, 'CELERY_BALANCE_HYSTERESIS'),
                DEFAULT_HYSTERESIS_RATIO,
            ),
        ),
        cluster=cluster,
        cluster_role=role,
        node_id=node_id,
        node_ttl_sec=node_ttl,
        plan_ttl_sec=plan_ttl,
        egress_url=_pick(environ, 'CELERY_CLUSTER_EGRESS_URL'),
        auto_placement=auto_placement,
        quarantine_ttl_sec=quarantine_ttl,
    )
