# Inter-service dependency validation

Six Railway resources. Validated against the codebase (`app/celery_app.py`,
`app/workers/queues.py`, `app/workers/beat_schedule.py`, `app/db/session.py`,
`app/core/redis.py`, `frontend/next.config.mjs`).

## Dependency matrix

| Service | Postgres | Redis | Other | Notes |
|---|---|---|---|---|
| **api** | ✅ async (`+asyncpg`) + sync (`+psycopg`) for migrations | ✅ dedup keys, AI NX lock, conv lock | — | Runs `alembic upgrade head` on boot (advisory-locked) |
| **worker** | ✅ sync (`+psycopg`) task sessions | ✅ broker + result backend + AI lock | Meta API, Anthropic API | Consumes all queues; waits for schema before start |
| **scheduler** | ✅ (beat tasks query app tables) | ✅ broker (publishes beat tasks) | — | Exactly 1 replica; waits for schema |
| **frontend** | — | — | api public URL | `BACKEND_URL` rewrites + `NEXT_PUBLIC_*` |
| **postgres** | managed plugin | — | — | `${{Postgres.DATABASE_URL}}` |
| **redis** | — | managed plugin | — | `${{Redis.REDIS_URL}}` |

## Validated invariants

- **Broker/backend fallback**: `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`
  empty → `field_validator` defaults both to `REDIS_URL`. api, worker and
  scheduler therefore share one Redis instance as the Celery transport.
- **Queues consumed only by worker**: `start-worker.sh` passes
  `-Q default,outbound,ai,analytics`. `TASK_ROUTES` in
  `app/workers/queues.py` maps every module's tasks onto these queues. No
  queue is consumed by api or scheduler.
- **Beat schedule consumed only by scheduler**: `BEAT_SCHEDULE`
  (`scheduler_tick`, `expire_stale_locks`, `aggregate_daily_metrics`) is
  published by celery-beat in the scheduler service and executed by worker.
  Running >1 scheduler duplicates every firing — guarded by the `_scaling`
  note in `scheduler.json`.
- **No service-to-service HTTP/imports**: cross-module work goes through
  Celery tasks / Redis, not direct service calls (architectural invariant #2).
  The only network edge between custom services is frontend → api.
- **DSN normalization**: `DATABASE_URL` may be Railway's plain
  `postgresql://`. `Settings.DATABASE_URL_ASYNC` → `+asyncpg` (FastAPI engine),
  `Settings.DATABASE_URL_SYNC` → `+psycopg` (Alembic + Celery). Both derived
  from the single `DATABASE_URL` var.

## Boot ordering

1. `postgres`, `redis` (managed) — available first.
2. `api` — applies migrations under a Postgres advisory lock (safe with
   multiple replicas; the second waits).
3. `worker`, `scheduler` — `wait_for_schema.py` blocks (≤60s) until
   `alembic_version` exists, so they never crash-loop on a missing schema.
4. `frontend` — only needs the api public domain to be routable.
