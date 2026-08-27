"""Redis client factories.

Sync (used by Celery tasks) and async (used by FastAPI handlers) clients
share the same `REDIS_URL`. Both are constructed lazily — importing this
module is side-effect free.

Fixes applied:
  Msg-I8 — get_async_redis() had @lru_cache, binding the redis.asyncio.Redis
            client to the event loop that first called it. Subsequent calls
            from a *different* event loop (e.g. after hot-reload or in tests)
            would raise "Event loop is closed" or "Future is attached to a
            different loop".

            Fix: only the underlying ConnectionPool is cached (pools are
            loop-agnostic in redis-py ≥ 4.2). A thin Redis wrapper is created
            fresh per call from the shared pool — no loop binding, no cost.

  Msg-I9 — get_sync_redis() had @lru_cache, which survives Celery's
            worker fork. The parent process creates one Redis client (and its
            connection pool) before forking; after fork the pool's file
            descriptors are shared between parent and child, leading to
            interleaved reads/writes and protocol framing errors.

            Fix: the lru_cache is cleared in a worker_process_init signal
            handler in celery_app.py so each worker process creates its own
            fresh client after the fork.
"""

from __future__ import annotations

from functools import lru_cache

import redis as redis_sync
import redis.asyncio as redis_async

from app.core.config import get_settings

# Inbound webhook deduplication (DSD §4.1 — duplicate webhook ignored).
WEBHOOK_DEDUP_PREFIX = "wa:dedup:meta_msg:"
WEBHOOK_DEDUP_TTL_SECONDS = 60 * 60 * 24  # 24h

# Status-update dedup (Meta replays statuses).
STATUS_DEDUP_PREFIX = "wa:dedup:meta_status:"
STATUS_DEDUP_TTL_SECONDS = 60 * 60 * 6  # 6h


# --------------------------------------------------------------------------- #
# Sync client (Celery tasks)                                                   #
# --------------------------------------------------------------------------- #

@lru_cache
def get_sync_redis() -> redis_sync.Redis:
    """Return the process-level sync Redis client.

    The @lru_cache is intentional here: a single client per process is
    correct for sync (non-forked) use.  After a Celery worker *fork* the
    cache is cleared by the worker_process_init signal in celery_app.py so
    each child process gets its own fresh client.
    """
    settings = get_settings()
    return redis_sync.Redis.from_url(settings.REDIS_URL, decode_responses=True)


# --------------------------------------------------------------------------- #
# Async client (FastAPI handlers)                                              #
# --------------------------------------------------------------------------- #

@lru_cache
def _get_async_connection_pool() -> redis_async.ConnectionPool:
    """Return a shared async connection pool.

    ConnectionPool instances are not bound to any event loop in redis-py ≥ 4.2,
    so caching the pool with @lru_cache is safe across event-loop boundaries.
    """
    settings = get_settings()
    return redis_async.ConnectionPool.from_url(
        settings.REDIS_URL, decode_responses=True
    )


def get_async_redis() -> redis_async.Redis:
    """Return an async Redis client backed by the shared connection pool.

    Msg-I8 fix: the Redis *client* wrapper is created fresh on each call
    (cheap — it holds no state beyond the pool reference).  The underlying
    ConnectionPool is shared and cached, so connection reuse is preserved.
    No event-loop binding occurs at this level.
    """
    return redis_async.Redis(connection_pool=_get_async_connection_pool())


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

# DSD §11 — "Redis Failure → pause outbound dispatch". A cheap liveness
# probe used by the outbound/campaign Celery tasks to decide whether to
# proceed or reschedule. It must NEVER raise: any failure (connection
# refused, timeout, auth) is treated as "Redis is down".
REDIS_HEALTH_TIMEOUT_SECONDS = 1.0


def redis_healthy() -> bool:
    """Return True iff a sync ``PING`` round-trips within the timeout.

    Centralised so the outbound dispatch gate has a single definition of
    "Redis is up". Swallows every exception by design — callers branch on
    the bool, they never see an error from here.
    """
    try:
        settings = get_settings()
        probe = redis_sync.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=REDIS_HEALTH_TIMEOUT_SECONDS,
            socket_timeout=REDIS_HEALTH_TIMEOUT_SECONDS,
        )
        try:
            return bool(probe.ping())
        finally:
            try:
                probe.close()
            except Exception:
                pass
    except Exception:
        return False


def claim_dedup_key(
    client: redis_sync.Redis,
    key: str,
    *,
    ttl: int = WEBHOOK_DEDUP_TTL_SECONDS,
) -> bool:
    """Atomically claim a dedup key. Returns True if newly claimed, False if already seen.

    Uses SET NX EX so concurrent workers compete safely.
    """
    return bool(client.set(key, "1", nx=True, ex=ttl))
