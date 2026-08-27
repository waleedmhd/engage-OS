"""Integration coverage for AssignmentRepository.

Exercises both query methods against real Postgres so the round-robin
subquery (correlated scalar subquery + NULLS FIRST ordering) is validated
against the actual SQL dialect rather than skipped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.assignments.repository import AssignmentRepository
from app.modules.auth.models import User
from app.modules.contacts.models import Contact
from app.modules.conversations.models import Conversation


def _user(session, *, role: str, is_active: bool = True) -> User:
    u = User(
        id=uuid.uuid4(),
        email=f"u{uuid.uuid4().hex[:10]}@test.local",
        name="U",
        hashed_password="$2b$12$" + "a" * 53,
        role=role,
        is_active=is_active,
    )
    session.add(u)
    return u


@pytest.mark.asyncio
async def test_list_active_agents_filters_role_and_active(async_pg_session):
    agent = _user(async_pg_session, role="agent")
    admin = _user(async_pg_session, role="admin")
    inactive = _user(async_pg_session, role="agent", is_active=False)  # excluded
    await async_pg_session.flush()

    repo = AssignmentRepository(async_pg_session)
    agents = await repo.list_active_agents()

    ids = {u.id for u in agents}
    assert agent.id in ids
    assert admin.id in ids
    assert inactive.id not in ids


@pytest.mark.asyncio
async def test_next_round_robin_agent_prefers_unassigned(async_pg_session):
    busy = _user(async_pg_session, role="agent")
    fresh = _user(async_pg_session, role="agent")
    await async_pg_session.flush()

    contact = Contact(
        id=uuid.uuid4(),
        phone=f"+1888{uuid.uuid4().int % 10_000_000:07d}",
        name="C",
        status="active",
        marketing_opt_out=False,
    )
    async_pg_session.add(contact)
    await async_pg_session.flush()

    # `busy` already holds a lock; `fresh` has none -> NULLS FIRST puts fresh first.
    conv = Conversation(
        id=uuid.uuid4(),
        contact_id=contact.id,
        state="NEW",
        ai_enabled=True,
        locked_by=busy.id,
        lock_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    async_pg_session.add(conv)
    await async_pg_session.flush()

    repo = AssignmentRepository(async_pg_session)
    picked = await repo.next_round_robin_agent()

    assert picked is not None
    assert picked.id == fresh.id
