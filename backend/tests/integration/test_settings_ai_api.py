"""Integration: typed /settings/ai PUT->GET round-trip + audit row.

Reuses the admin-JWT + committed_db harness from test_settings_api.py.
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
async def test_ai_settings_roundtrip_and_audit(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    get0 = await client.get("/api/v1/settings/ai", headers=auth)
    assert get0.status_code == 200, get0.text
    data = get0.json()
    assert data["kill_switch"] is False
    assert data["auto_send_enabled"] is True
    assert data["test_numbers"] == []
    assert data["tag_suggestions_enabled"] is True
    assert data["response_generation_enabled"] is True

    put = await client.put(
        "/api/v1/settings/ai", json={"kill_switch": True}, headers=auth
    )
    assert put.status_code == 200, put.text
    assert put.json()["kill_switch"] is True
    assert put.json()["auto_send_enabled"] is True

    get1 = await client.get("/api/v1/settings/ai", headers=auth)
    assert get1.json()["kill_switch"] is True

    rows = (
        committed_db.execute(
            select(AuditLog).where(AuditLog.entity_type == "AppSetting")
        )
        .scalars()
        .all()
    )
    assert len(rows) >= 1
    assert all(r.action == "update" for r in rows)


@pytest.mark.asyncio
async def test_ai_settings_admin_only(committed_db, client):
    agent = make_user(committed_db, role="agent")
    committed_db.commit()
    r = await client.get("/api/v1/settings/ai", headers=_token(agent))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_ai_settings_test_numbers_roundtrip(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    put = await client.put(
        "/api/v1/settings/ai",
        json={"test_numbers": ["+123", "+456"]},
        headers=auth,
    )
    assert put.status_code == 200, put.text
    assert put.json()["test_numbers"] == ["+123", "+456"]

    get1 = await client.get("/api/v1/settings/ai", headers=auth)
    assert get1.json()["test_numbers"] == ["+123", "+456"]


@pytest.mark.asyncio
async def test_ai_settings_multiple_fields_roundtrip(committed_db, client):
    admin = make_user(committed_db, role="admin")
    committed_db.commit()
    auth = _token(admin)

    put = await client.put(
        "/api/v1/settings/ai",
        json={
            "test_numbers": ["+999"],
            "tag_suggestions_enabled": False,
            "response_generation_enabled": False,
        },
        headers=auth,
    )
    assert put.status_code == 200, put.text
    data = put.json()
    assert data["test_numbers"] == ["+999"]
    assert data["tag_suggestions_enabled"] is False
    assert data["response_generation_enabled"] is False
    assert data["kill_switch"] is False

    get1 = await client.get("/api/v1/settings/ai", headers=auth)
    assert get1.json()["test_numbers"] == ["+999"]
    assert get1.json()["tag_suggestions_enabled"] is False
