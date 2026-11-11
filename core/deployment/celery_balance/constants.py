"""Константы балансировщика Celery (без привязки к железу хоста)."""

from __future__ import annotations

FOOTPRINT_FILENAME = 'task_footprint.yaml'
DECISION_FILENAME = 'decision.json'
HISTORY_FILENAME = 'history.jsonl'
# Потолок на диске: иначе postrun каждой задачи раздувает jsonl до гигабайт,
# а stats_by_queue зависает на полном read_text.
HISTORY_MAX_BYTES = 32 * 1024 * 1024
# Для медианы достаточно хвоста; не читаем весь файл в память.
HISTORY_READ_MAX_BYTES = 8 * 1024 * 1024
HISTORY_MAX_SAMPLES_PER_QUEUE = 500
QUEUES_CACHE_NAME = 'celery_queues.bin'
BEAT_SCHEDULE_CACHE_NAME = 'celery_beat_schedule.bin'
SIGNATURE_SEPARATOR = b'\n---SIGNATURE---\n'

MODE_OFF = 'off'
MODE_RECOMMEND = 'recommend'
MODE_AUTO = 'auto'
MODES = frozenset({MODE_OFF, MODE_RECOMMEND, MODE_AUTO})
DEFAULT_MODE = MODE_AUTO

CLASS_LIGHT = 'light'
CLASS_MEDIUM = 'medium'
CLASS_HEAVY = 'heavy'
TASK_CLASSES = frozenset({CLASS_LIGHT, CLASS_MEDIUM, CLASS_HEAVY})

# Generic defaults — не инвентарь конкретной машины.
CLASS_DEFAULTS: dict[str, dict[str, float | int]] = {
    CLASS_LIGHT: {
        'ram_mb': 128,
        'cpu_units': 0.25,
        'vram_mb': 0,
        'max_parallel': 8,
    },
    CLASS_MEDIUM: {
        'ram_mb': 256,
        'cpu_units': 1.0,
        'vram_mb': 0,
        'max_parallel': 4,
    },
    CLASS_HEAVY: {
        'ram_mb': 1024,
        'cpu_units': 2.0,
        'vram_mb': 0,
        'max_parallel': 1,
    },
}

DEFAULT_OS_RESERVE_RAM_MB = 1024
DEFAULT_RESERVE_CPU = 1.0
DEFAULT_MIN_CONCURRENCY = 1
DEFAULT_WATCH_INTERVAL_SEC = 30.0
DEFAULT_HYSTERESIS_RATIO = 0.2
DEFAULT_HISTORY_MIN_SAMPLES = 5
DEFAULT_PREFETCH = 4
HEAVY_PREFETCH = 1
DEFAULT_RESERVE_LIGHT = 2
DEFAULT_QUEUE_NAME = 'default'
DEFAULT_GPU_UTIL_CAP = 80.0

CLUSTER_OFF = 'off'
CLUSTER_ON = 'on'
CLUSTER_MODES = frozenset({CLUSTER_OFF, CLUSTER_ON})
DEFAULT_CLUSTER = CLUSTER_OFF
ROLE_MANAGER = 'manager'
ROLE_AGENT = 'agent'
CLUSTER_ROLES = frozenset({ROLE_MANAGER, ROLE_AGENT})
DEFAULT_CLUSTER_ROLE = ROLE_MANAGER
DEFAULT_NODE_TTL_SEC = 90
# План в Redis живёт дольше узла: один долгий круг watch не должен гасить ключ.
DEFAULT_PLAN_TTL_SEC = 600
DEFAULT_PLAN_TTL_MIN_SEC = 120
LAST_PLAN_FILENAME = 'last_plan.json'

PLACEMENT_PRIMARY = 'primary'
PLACEMENT_ANY = 'any'
PLACEMENT_GPU = 'gpu'
PLACEMENT_AGENT = 'agent'
PLACEMENT_AUTO = 'auto'
PLACEMENTS = frozenset({
    PLACEMENT_PRIMARY,
    PLACEMENT_ANY,
    PLACEMENT_GPU,
    PLACEMENT_AGENT,
    PLACEMENT_AUTO,
})
DEFAULT_PLACEMENT = PLACEMENT_AUTO

AUTO_PLACEMENT_AGENT = 'agent'
AUTO_PLACEMENT_OFF = 'off'
AUTO_PLACEMENTS = frozenset({AUTO_PLACEMENT_AGENT, AUTO_PLACEMENT_OFF})
DEFAULT_AUTO_PLACEMENT = AUTO_PLACEMENT_AGENT
DEFAULT_QUARANTINE_TTL_SEC = 7 * 24 * 3600

NODE_KEY_PREFIX = 'celery_balance:node:'
PLAN_KEY_PREFIX = 'celery_balance:plan:'
QUARANTINE_KEY_PREFIX = 'celery_balance:quarantine:'

# Роли, которые нельзя вытеснять бюджетом Celery.
RESERVE_ROLES = frozenset({
    'api',
    'media-api',
    'client',
    'redis',
    'nginx',
    'postgres',
    'meilisearch',
    'jupyter',
    'celery-beat',
})
CELERY_WORKER_ROLE = 'celery-worker'

REDIS_CELERY_BROKER_DB_DEFAULT = 2
