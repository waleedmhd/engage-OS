# Railway service configuration

EngageOS deploys as **six** Railway resources:

| Service | Type | Root | Start command |
|---|---|---|---|
| `engageos-api` | Custom (Dockerfile) | `backend/` | `bash scripts/start-api.sh` (default in `backend/railway.json`) |
| `engageos-worker` | Custom (Dockerfile) | `backend/` | `bash scripts/start-worker.sh` (Custom Start Command override) |
| `engageos-scheduler` | Custom (Dockerfile) | `backend/` | `bash scripts/start-scheduler.sh` (Custom Start Command override) |
| `engageos-frontend` | Custom (Dockerfile) | `frontend/` | `node server.js` (default in `frontend/railway.json`) |
| `postgres` | Managed plugin | — | — |
| `redis` | Managed plugin | — | — |

**How Railway picks up the build:** Railway reads a `railway.json` at each
service's **Root Directory**. The actual auto-applied files are
[`backend/railway.json`](../../backend/railway.json) (api/worker/scheduler) and
[`frontend/railway.json`](../../frontend/railway.json). All three backend
services share `backend/railway.json` (default start command = API), so
**worker and scheduler must set a Custom Start Command** in their Railway
service settings (`bash scripts/start-worker.sh` / `bash scripts/start-scheduler.sh`).

The JSON files **in this `infra/railway/` directory are documentation** of each
service's required env vars, start command, and scaling rules — not
auto-applied. Set the Root Directory per service so Railway finds the right
`railway.json`.

## Quickstart

```bash
railway login
railway link <project>

# Add managed plugins.
railway add --plugin postgresql
railway add --plugin redis

# Add custom services from this repo.
railway up --service engageos-api
railway up --service engageos-worker
railway up --service engageos-scheduler
railway up --service engageos-frontend
```

Then configure each service's variables to match `_requiredEnv` in its JSON
file. Reference `${{Postgres.DATABASE_URL}}` and `${{Redis.REDIS_URL}}`
to wire managed plugins automatically.

## Reference docs

- [`../../docs/railway-deployment.md`](../../docs/railway-deployment.md) — full operator setup/mounting runbook
- [`ENVIRONMENT.md`](ENVIRONMENT.md) — per-service environment variable tables
- [`DEPENDENCIES.md`](DEPENDENCIES.md) — validated inter-service dependency matrix
- [`SCALING.md`](SCALING.md) — replica/concurrency recommendations
- [`worker-split.example/`](worker-split.example/) — optional per-queue worker services
