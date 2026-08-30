"""Idempotently create an admin user from SEED_ADMIN_* env vars.

No-op (exits 0, prints nothing) unless both SEED_ADMIN_EMAIL and
SEED_ADMIN_PASSWORD are set, so it's safe to leave wired into
start-api.sh permanently. Existing users are left untouched (ON
CONFLICT DO NOTHING) — this only ever creates the first admin.

SEED_ADMIN_DELETE_EMAIL, if set, deletes that user first — a one-off
escape hatch for correcting a bad SEED_ADMIN_EMAIL from a prior run
(e.g. a value rejected by login's EmailStr validation) without needing
DB shell access.

Usage (from backend/):
  python -m scripts.seed_admin

On Railway:
  railway run --service engage-OS "python -m scripts.seed_admin"
"""

from __future__ import annotations

import os

from sqlalchemy import text

from app.core.security import hash_password
from app.db.session import sync_session_factory


def main() -> int:
    email = os.environ.get("SEED_ADMIN_EMAIL", "").strip()
    password = os.environ.get("SEED_ADMIN_PASSWORD", "")
    name = os.environ.get("SEED_ADMIN_NAME", "Admin").strip()
    delete_email = os.environ.get("SEED_ADMIN_DELETE_EMAIL", "").strip()

    if not email or not password:
        return 0

    hashed = hash_password(password)
    with sync_session_factory() as session:
        if delete_email:
            deleted = session.execute(
                text("DELETE FROM users WHERE email = :email"),
                {"email": delete_email},
            )
            session.commit()
            if deleted.rowcount:
                print(f"seed_admin: deleted user email={delete_email}")
        result = session.execute(
            text(
                "INSERT INTO users (email, name, hashed_password, role, is_active) "
                "VALUES (:email, :name, :hashed, 'admin', true) "
                "ON CONFLICT (email) DO NOTHING "
                "RETURNING id"
            ),
            {"email": email, "name": name, "hashed": hashed},
        )
        row = result.first()
        session.commit()

    if row:
        print(f"seed_admin: created admin user id={row[0]} email={email}")
    else:
        print(f"seed_admin: user email={email} already exists; no changes made")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
