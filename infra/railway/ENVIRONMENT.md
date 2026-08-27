# Railway environment variables

Keys are case-sensitive and map 1:1 to `backend/app/core/config.py:Settings`.
Use Railway reference variables (`${{Postgres.*}}`, `${{Redis.*}}`) so the
managed plugins wire automatically. Empty broker/backend default to `REDIS_URL`.

## Shared (api, worker, scheduler)

| Var | Value on Railway | Notes |
|---|---|---|
| `ENV` | `production` | Triggers required-secret validation |
| `LOG_LEVEL` | `INFO` | |
| `LOG_FORMAT` | `json` | Structured logs |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Plain `postgresql://`; app derives async (`+asyncpg`) and sync (`+psycopg`) forms |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | |
| `CELERY_BROKER_URL` | *(empty)* | Defaults to `REDIS_URL` |
| `CELERY_RESULT_BACKEND` | *(empty)* | Defaults to `REDIS_URL` |

## api (engageos-api) — adds

| Var | Value | Notes |
|---|---|---|
| `JWT_SECRET` | random ≥32 chars | **Required**; must differ from default |
| `JWT_ALGORITHM` | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | |
| `CORS_ORIGINS` | `https://<frontend-domain>` | Plain string / comma list, **not** JSON |
| `FRONTEND_URL` | `https://<frontend-domain>` | |
| `META_APP_SECRET` | from Meta | **Required** in production (Msg-C3) |
| `META_VERIFY_TOKEN` | your token | **Required** in production (Msg-M11) |
| `META_ACCESS_TOKEN` | from Meta | |
| `META_PHONE_NUMBER_ID` | from Meta | |
| `META_API_VERSION` | `v19.0` | |
| `META_SEND_RATE_LIMIT` | `60` | msgs/sec guard (WABA ≈80/s) |
| `ANTHROPIC_API_KEY` | from Anthropic | **Required** in production |

## worker (engageos-worker) — adds

Same Meta/Anthropic keys as api (tasks call those clients). Optional tuning:

| Var | Default | Notes |
|---|---|---|
| `CELERY_QUEUES` | `default,outbound,ai,analytics` | Override to split workers |
| `CELERY_CONCURRENCY` | `2` | Per-process worker concurrency |
| `WAIT_FOR_SCHEMA` | `1` | Set `0` to skip the migration-readiness wait |

## scheduler (engageos-scheduler) — adds

Shared keys only. Optional: `CELERY_BEAT_SCHEDULE_FILE` (default
`/tmp/celerybeat-schedule`), `WAIT_FOR_SCHEMA`.

## frontend (engageos-frontend)

| Var | Value | Notes |
|---|---|---|
| `ENV` | `production` | |
| `BACKEND_URL` | `https://<api-domain>` | Server-side rewrites |
| `NEXT_PUBLIC_API_URL` | `https://<api-domain>/api/v1` | Baked at build time |
| `NEXT_PUBLIC_WS_URL` | `wss://<api-domain>/ws` | Baked at build time |
