#!/usr/bin/env bash
# Apply Alembic migrations. Run from `backend/`.
set -euo pipefail
exec alembic upgrade head
