"""Unit tests for AuditService read path — repository is AsyncMocked (P1.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.audit.service import AuditService


def _make_service():
    svc = AuditService(AsyncMock())
    svc.repo = AsyncMock()
    return svc


def _row(**over):
    base = dict(
        id=uuid.uuid4(),
        actor_type="user",
        actor_id=uuid.uuid4(),
        action="update",
        entity_type="AppSetting",
        entity_id=uuid.uuid4(),
        before_state={"v": 1},
        after_state={"v": 2},
        created_at=datetime.now(UTC),
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_list_logs_uses_real_count_not_len():
    svc = _make_service()
    svc.repo.list_logs.return_value = [_row(), _row()]
    svc.repo.count_logs.return_value = 57

    page = await svc.list_logs(page=2, page_size=2, entity_type="AppSetting")

    assert page.total == 57
    assert page.page == 2
    assert page.page_size == 2
    assert len(page.items) == 2
    svc.repo.count_logs.assert_awaited_once_with(
        entity_type="AppSetting", entity_id=None, actor_id=None, action=None
    )


@pytest.mark.asyncio
async def test_list_logs_serializes_uuids_to_str():
    svc = _make_service()
    rid = uuid.uuid4()
    svc.repo.list_logs.return_value = [_row(id=rid, actor_id=None, entity_id=None)]
    svc.repo.count_logs.return_value = 1

    page = await svc.list_logs()

    item = page.items[0]
    assert item.id == str(rid)
    assert item.actor_id is None
    assert item.entity_id is None
    assert item.before_state == {"v": 1}


@pytest.mark.asyncio
async def test_list_logs_passes_all_filters():
    svc = _make_service()
    svc.repo.list_logs.return_value = []
    svc.repo.count_logs.return_value = 0
    aid = uuid.uuid4()
    eid = uuid.uuid4()

    await svc.list_logs(
        entity_type="Conversation",
        entity_id=eid,
        actor_id=aid,
        action="approve",
    )

    svc.repo.list_logs.assert_awaited_once_with(
        page=1,
        page_size=50,
        entity_type="Conversation",
        entity_id=eid,
        actor_id=aid,
        action="approve",
    )
