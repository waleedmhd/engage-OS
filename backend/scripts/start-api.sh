#!/usr/bin/env bash
# Start the FastAPI service. Runs from the image WORKDIR (/app == backend root).
# `alembic upgrade head` is advisory-locked (see alembic/env.py) so concurrent
# replicas serialize safely.
set -euo pipefail

PORT="${PORT:-8000}"
LOG_LEVEL="${LOG_LEVEL:-info}"

alembic upgrade head
python -m scripts.seed_admin
# No-ops unless SEED_DEMO=1. Idempotent (uuid5 ids + ON CONFLICT DO NOTHING),
# so it is safe to leave wired in permanently, like seed_admin above.
# Never fatal: demo data is cosmetic, and under `set -e` a failure here would
# kill the container, which restarts and re-runs the seeder in a crash loop.
python -m scripts.seed_demo || echo "start-api: seed_demo failed, continuing"
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --log-level "${LOG_LEVEL,,}"
