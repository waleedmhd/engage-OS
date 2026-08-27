"""Integration: /settings/operational PUT->GET round-trip + audit rows.

Reuses the admin-JWT + committed_db harness (see test_settings_ai_api.py).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from tests.factories import make_user


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


@pytest.mark.asyncio
async def test_operational_roundtrip_and_audit(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    get0 = await client.get("/api/v1/settings/operational", headers=auth)
    assert get0.status_code == 200, get0.text
    body0 = get0.json()
    assert body0["timezone"]["tz"] == "UTC"
    assert body0["campaign_daily_cap"] == {"enabled": True, "limit": 800}
    assert body0["read_only_mode"]["enabled"] is False

    put = await client.put(
        "/api/v1/settings/operational",
        json={
            "read_only_mode": {"enabled": True},
            "campaign_daily_cap": {"enabled": True, "limit": 500},
        },
        headers=auth,
    )
    assert put.status_code == 200, put.text
    assert put.json()["read_only_mode"]["enabled"] is True
    assert put.json()["campaign_daily_cap"]["limit"] == 500

    get1 = await client.get("/api/v1/settings/operational", headers=auth)
    assert get1.json()["campaign_daily_cap"]["limit"] == 500

    rows = (
        committed_db.execute(
            select(AuditLog).where(AuditLog.entity_type == "AppSetting")
        )
        .scalars()
        .all()
    )
    # Two groups changed -> at least two AppSetting audit rows.
    assert len(rows) >= 2
    assert all(r.action == "update" for r in rows)


@pytest.mark.asyncio
async def test_operational_admin_only(committed_db, client):
    agent = make_user(committed_db, role="agent")
    committed_db.commit()
    r = await client.get(
        "/api/v1/settings/operational", headers=_token(agent)
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_operational_rejects_bad_timezone(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    r = await client.put(
        "/api/v1/settings/operational",
        json={"timezone": {"tz": "Mars/Olympus"}},
        headers=_token(admin),
    )
    assert r.status_code == 422
