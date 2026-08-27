"""P2.2 — concurrent `alembic upgrade head` is serialized by the advisory
lock in alembic/env.py (multi-replica API safety, DSD §8).

Spawns two `alembic upgrade head` subprocesses at once against the test DB.
With the session-level `pg_advisory_lock` in env.py the second blocks until
the first finishes (then its upgrade is a no-op); without it the two would
race the `alembic_version` table and can deadlock / double-apply. We assert
BOTH exit 0.

Requires docker-compose.test.yml. Auto-marked `integration`.
"""

from __future__ import annotations

import concurrent.futures
import os
import subprocess
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]


def _run_upgrade() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(_BACKEND),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_concurrent_alembic_upgrade_is_serialized(_pg_session_ready) -> None:
    # `_pg_session_ready` (conftest) skips if Postgres is unreachable and has
    # already applied migrations once, so each concurrent run here exercises
    # the lock path and resolves to a no-op upgrade.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(_run_upgrade)
        f2 = ex.submit(_run_upgrade)
        r1, r2 = f1.result(), f2.result()

    assert r1.returncode == 0, f"first upgrade failed:\n{r1.stdout}\n{r1.stderr}"
    assert r2.returncode == 0, f"second upgrade failed:\n{r2.stdout}\n{r2.stderr}"
