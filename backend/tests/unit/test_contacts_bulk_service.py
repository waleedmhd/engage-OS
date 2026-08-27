"""Unit tests for ContactService.bulk_update / bulk_delete.

Uses the `async_pg_session` fixture (function-scoped, SAVEPOINT-rolled-back)
defined in tests/conftest.py. No Celery or HTTP layer is exercised here.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.contacts.schemas import (
    BulkPatch,
    ContactCreateRequest,
)
from app.modules.contacts.service import ContactService


@pytest.fixture
async def three_contacts(async_pg_session):
    svc = ContactService(async_pg_session)
    actor = uuid.uuid4()
    out = []
    for i in range(3):
        c = await svc.create_contact(
            payload=ContactCreateRequest(phone=f"+1555000000{i}"),
            actor_id=actor,
        )
        out.append(c)
    await async_pg_session.flush()
    return out, actor


@pytest.mark.asyncio
class TestBulkUpdate:
    async def test_happy_path_status(self, async_pg_session, three_contacts):
        contacts, actor = three_contacts
        svc = ContactService(async_pg_session)
        res = await svc.bulk_update(
            ids=[c.id for c in contacts],
            patch=BulkPatch(status="blocked"),
            actor_id=actor,
        )
        assert res.count == 3
        assert res.failed == []
        for c in contacts:
            await async_pg_session.refresh(c)
            assert c.status == "blocked"

    async def test_partial_failure_missing_id(self, async_pg_session, three_contacts):
        contacts, actor = three_contacts
        ghost = uuid.uuid4()
        svc = ContactService(async_pg_session)
        res = await svc.bulk_update(
            ids=[contacts[0].id, ghost, contacts[1].id],
            patch=BulkPatch(status="follow_up"),
            actor_id=actor,
        )
        assert res.count == 2
        assert len(res.failed) == 1
        assert res.failed[0].id == ghost
        assert res.failed[0].error == "not_found"

    async def test_writes_single_audit_row(self, async_pg_session, three_contacts):
        from sqlalchemy import select

        from app.modules.audit.models import AuditLog

        contacts, actor = three_contacts
        baseline = (
            await async_pg_session.execute(
                select(AuditLog).where(AuditLog.action == "contact.bulk_updated")
            )
        ).scalars().all()
        assert baseline == []

        svc = ContactService(async_pg_session)
        await svc.bulk_update(
            ids=[c.id for c in contacts],
            patch=BulkPatch(status="active"),
            actor_id=actor,
        )
        rows = (
            await async_pg_session.execute(
                select(AuditLog).where(AuditLog.action == "contact.bulk_updated")
            )
        ).scalars().all()
        assert len(rows) == 1
        meta = rows[0].after_state or {}
        assert meta.get("count") == 3
        assert meta.get("failed_count") == 0


@pytest.mark.asyncio
class TestBulkDelete:
    async def test_happy_path(self, async_pg_session, three_contacts):
        contacts, actor = three_contacts
        svc = ContactService(async_pg_session)
        res = await svc.bulk_delete(
            ids=[c.id for c in contacts], actor_id=actor
        )
        assert res.count == 3
        assert res.failed == []
        for c in contacts:
            assert await svc._repo.get(c.id) is None

    async def test_partial_failure_missing_id(self, async_pg_session, three_contacts):
        contacts, actor = three_contacts
        ghost = uuid.uuid4()
        svc = ContactService(async_pg_session)
        res = await svc.bulk_delete(
            ids=[contacts[0].id, ghost], actor_id=actor
        )
        assert res.count == 1
        assert len(res.failed) == 1
        assert res.failed[0].id == ghost
        assert res.failed[0].error == "not_found"
