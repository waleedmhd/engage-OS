#!/usr/bin/env bash
# Start a Celery worker. Runs from the image WORKDIR (/app == backend root).
set -euo pipefail

LOG_LEVEL="${LOG_LEVEL:-INFO}"
QUEUES="${CELERY_QUEUES:-default,outbound,ai,analytics}"
CONCURRENCY="${CELERY_CONCURRENCY:-2}"

# Wait for the API service to have applied migrations before consuming tasks.
# Skippable via WAIT_FOR_SCHEMA=0 (e.g. local dev where the API isn't separate).
# Invoke as a module (`-m`) so the WORKDIR (/app) is on sys.path and `app`
# imports — `python scripts/wait_for_schema.py` puts /app/scripts on the path
# instead, which raises ModuleNotFoundError: No module named 'app'.
if [ "${WAIT_FOR_SCHEMA:-1}" != "0" ]; then
  python -m scripts.wait_for_schema
fi

exec celery -A app.celery_app.celery_app worker \
  -l "$LOG_LEVEL" \
  -Q "$QUEUES" \
  --concurrency="$CONCURRENCY"
