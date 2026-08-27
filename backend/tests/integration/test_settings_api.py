"""Integration tests for the Settings API (P1.2).

Drives router → service → repository with a real admin JWT and the
real-committing `committed_db`, and asserts the PUT writes an audit row.
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
async def test_put_then_get_and_list(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    put = await client.put(
        "/api/v1/settings/campaign.global_rate_per_second",
        json={"value": {"rate": 25}},
        headers=auth,
    )
    assert put.status_code == 200, put.text
    assert put.json()["value"] == {"rate": 25}

    got = await client.get(
        "/api/v1/settings/campaign.global_rate_per_second", headers=auth
    )
    assert got.status_code == 200
    assert got.json()["value"] == {"rate": 25}

    # idempotent upsert — second PUT updates in place.
    put2 = await client.put(
        "/api/v1/settings/campaign.global_rate_per_second",
        json={"value": {"rate": 40}},
        headers=auth,
    )
    assert put2.status_code == 200
    assert put2.json()["value"] == {"rate": 40}

    lst = await client.get("/api/v1/settings", headers=auth)
    assert lst.status_code == 200
    keys = [s["key"] for s in lst.json()]
    assert "campaign.global_rate_per_second" in keys

    # audit trail covers the config change (DSD §9).
    rows = committed_db.execute(
        select(AuditLog).where(AuditLog.entity_type == "AppSetting")
    ).scalars().all()
    assert len(rows) >= 2
    assert all(r.action == "update" for r in rows)
    assert any(r.before_state is not None for r in rows)


@pytest.mark.asyncio
async def test_get_unknown_key_404(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    r = await client.get("/api/v1/settings/does.not.exist", headers=_token(admin))
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_settings_admin_only(committed_db, client):
    agent = make_user(committed_db, role="agent")
    committed_db.commit()
    r = await client.get("/api/v1/settings", headers=_token(agent))
    assert r.status_code == 403
