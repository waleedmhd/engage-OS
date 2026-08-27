"""Assignment constants (DSD §4.8)."""

from enum import StrEnum


class AssignmentStrategy(StrEnum):
    MANUAL = "manual"
    ROUND_ROBIN = "round_robin"


# Lock TTL re-exported for convenience.
LOCK_RENEWAL_INTERVAL_SECONDS: int = 30

# Periodic sweep interval — how often `expire_stale_locks_task` fires from
# Celery Beat. Matches LOCK_RENEWAL_INTERVAL_SECONDS so worst-case latency
# between TTL expiry and reaper-driven release is bounded to one tick.
LOCK_EXPIRY_SWEEP_INTERVAL_SECONDS: int = 30

# Per-tick cap on the number of expired locks the sweep reaps in a single
# task invocation. Prevents an unbounded UPDATE if a large backlog builds up
# (e.g. after a worker outage). The next tick will pick up the remainder.
LOCK_EXPIRY_SWEEP_BATCH_LIMIT: int = 200
