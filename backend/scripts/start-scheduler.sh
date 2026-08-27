#!/usr/bin/env bash
# Start Celery beat (scheduler). Runs from the image WORKDIR (/app == backend root).
set -euo pipefail

LOG_LEVEL="${LOG_LEVEL:-INFO}"
SCHEDULE_FILE="${CELERY_BEAT_SCHEDULE_FILE:-/tmp/celerybeat-schedule}"

# Wait for the API service to have applied migrations before scheduling tasks
# (the sweep/analytics beat tasks query application tables). Skippable via
# WAIT_FOR_SCHEMA=0.
# Invoke as a module (`-m`) so the WORKDIR (/app) is on sys.path and `app`
# imports — `python scripts/wait_for_schema.py` puts /app/scripts on the path
# instead, which raises ModuleNotFoundError: No module named 'app'.
if [ "${WAIT_FOR_SCHEMA:-1}" != "0" ]; then
  python -m scripts.wait_for_schema
fi

exec celery -A app.celery_app.celery_app beat \
  -l "$LOG_LEVEL" \
  --schedule "$SCHEDULE_FILE"
