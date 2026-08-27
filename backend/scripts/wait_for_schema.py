"""Block until the database is reachable and migrations have been applied.

Used by the worker and scheduler startup scripts so they don't crash-loop when
they boot before the API service has run `alembic upgrade head` (Railway starts
services in parallel). Readiness == the `alembic_version` table exists and has a
row.

Invoke as a module from `backend/` — `python -m scripts.wait_for_schema` — so
the working directory is on `sys.path` and `app` imports. Running it as a plain
script (`python scripts/wait_for_schema.py`) puts `backend/scripts` on the path
instead of `backend`, raising `ModuleNotFoundError: No module named 'app'`.
Exits 0 when ready, 1 on timeout.
"""

from __future__ import annotations

import sys
import time

import psycopg

from app.core.config import get_settings

TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 2


def _dsn() -> str:
    # psycopg wants a libpq DSN, not the SQLAlchemy "+psycopg" prefix.
    return get_settings().DATABASE_URL_SYNC.replace("postgresql+psycopg://", "postgresql://", 1)


def main() -> int:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    dsn = _dsn()
    last_err: str = ""
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM alembic_version LIMIT 1")
                    if cur.fetchone() is not None:
                        print("wait_for_schema: database ready (alembic_version present)")
                        return 0
                    last_err = "alembic_version table empty (migrations not yet applied)"
        except Exception as exc:
            last_err = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
        print(f"wait_for_schema: not ready ({last_err}); retrying...", flush=True)
        time.sleep(POLL_INTERVAL_SECONDS)

    print(
        f"wait_for_schema: timed out after {TIMEOUT_SECONDS}s waiting for "
        f"migrations. Last error: {last_err}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
