# Scaling recommendations

## api — horizontally scalable

Stateless request handlers. Scale replicas freely. Caveats:

- **Migrations**: every replica runs `alembic upgrade head` on boot. A
  Postgres session advisory lock (`alembic/env.py`) serializes them — only
  one migrates, the rest wait then no-op. Safe to scale during deploy.
- **DB pool**: effective Postgres connections ≈
  `replicas × (DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW)` (default 10+20).
  Keep below the Postgres plan's `max_connections`; lower the pool vars or add
  PgBouncer before scaling wide.

## worker — horizontally scalable, split by queue when load grows

Default: one service, all queues, `CELERY_CONCURRENCY=2`. To scale, either add
replicas or split into dedicated services using `CELERY_QUEUES` (see
`worker-split.example/`):

| Group | Queues | Why isolate |
|---|---|---|
| ai | `ai` | Claude AI cascade latency-bound; per-conversation Redis NX lock (180s TTL) caps real concurrency — scale replicas, not concurrency |
| outbound | `outbound` | Meta WABA limit ≈80 msg/s. Keep `replicas × CELERY_CONCURRENCY × per-task send rate` ≤ `META_SEND_RATE_LIMIT` |
| default | `default,analytics` | Sweep/rollup; bursty, CPU-light |

Tuning rules:
- `task_acks_late=True` + `worker_prefetch_multiplier=1` are set — a crashed
  worker redelivers in-flight tasks, so replicas are safe to add/remove.
- Don't raise `outbound` concurrency past the Meta rate budget.

## scheduler — pin to exactly 1 replica

celery-beat. **Never scale > 1** — duplicate beat instances double every
firing (`scheduler_tick`, `expire_stale_locks`, `aggregate_daily_metrics`),
causing duplicate sends and double sweeps. Disable autoscaling on this service.

## Postgres / Redis (managed plugins)

- **Postgres**: size by total pool across api + worker replicas (see above).
  Phase 6 analytics rollups run daily at 00:15 UTC — negligible steady load.
- **Redis**: single instance serves three roles — Celery broker/backend,
  webhook/status dedup keys (24h/6h TTL), and the AI per-conversation NX lock.
  Memory is dominated by the result backend; set a Redis maxmemory policy or
  `CELERY_RESULT_BACKEND` TTL if result volume grows.

## Recommended starting point

| Service | Replicas | Concurrency |
|---|---|---|
| api | 2 | — (uvicorn default) |
| worker | 1 (split to 2–3 by queue under load) | 2 |
| scheduler | 1 (fixed) | — |
| frontend | 1–2 | — |
