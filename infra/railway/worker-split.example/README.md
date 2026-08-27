# Worker split (optional, not deployed by default)

The default deployment runs a single `engageos-worker` consuming all queues.
Under load, replace it with these three dedicated services for isolation:

1. Create `engageos-worker-ai`, `engageos-worker-outbound`,
   `engageos-worker-default` from the JSON files here.
2. Set each service's `CELERY_QUEUES` / `CELERY_CONCURRENCY` per `_extraEnv`,
   plus the shared/required env vars (see `../ENVIRONMENT.md`).
3. **Delete or scale-to-zero the original `engageos-worker`** so each queue has
   exactly one owning service. (Two services on the same queue still works for
   throughput but defeats the isolation/rate-limit reasoning in `../SCALING.md`.)

These files are documentation/templates — Railway services are still created
via the dashboard or CLI (`railway up --service <name>`).
