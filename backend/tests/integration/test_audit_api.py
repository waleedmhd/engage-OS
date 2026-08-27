"""Integration tests for GET /audit-logs (P1.1).

Seeds AuditLog rows via the real-committing `committed_db` and drives the
HTTP API with a real admin JWT — exercises router → service → repository.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.security import create_access_token
from app.modules.audit.constants import ActorType, AuditAction
from app.modules.audit.models import AuditLog
from tests.factories import make_user


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


def _seed_logs(session, n: int, entity_type: str = "AppSetting") -> None:
    for i in range(n):
        session.add(
            AuditLog(
                id=uuid.uuid4(),
                actor_type=ActorType.USER.value,
                actor_id=uuid.uuid4(),
                action=AuditAction.UPDATE.value,
                entity_type=entity_type,
                entity_id=uuid.uuid4(),
                before_state={"v": i},
                after_state={"v": i + 1},
            )
        )


@pytest.mark.asyncio
async def test_audit_logs_paginated_real_total(committed_db, client):
    admin = make_user(committed_db, role="admin")
    _seed_logs(committed_db, 7)
    committed_db.commit()

    resp = await client.get(
        "/api/v1/audit-logs?page=1&page_size=3", headers=_token(admin)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 7
    assert body["page"] == 1
    assert body["page_size"] == 3
    assert len(body["items"]) == 3
    assert body["total"] > len(body["items"])
    assert body["items"][0]["before_state"] is not None


@pytest.mark.asyncio
async def test_audit_logs_entity_type_filter(committed_db, client):
    admin = make_user(committed_db, role="admin")
    _seed_logs(committed_db, 2, entity_type="AppSetting")
    _seed_logs(committed_db, 4, entity_type="Conversation")
    committed_db.commit()

    resp = await client.get(
        "/api/v1/audit-logs?entity_type=Conversation", headers=_token(admin)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 4
    assert all(i["entity_type"] == "Conversation" for i in body["items"])


@pytest.mark.asyncio
async def test_audit_logs_admin_only(committed_db, client):
    agent = make_user(committed_db, role="agent")
    committed_db.commit()

    resp = await client.get("/api/v1/audit-logs", headers=_token(agent))
    assert resp.status_code == 403, resp.text
