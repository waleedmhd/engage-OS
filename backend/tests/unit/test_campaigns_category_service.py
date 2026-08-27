"""Unit tests for CampaignCategoryService — repositories AsyncMocked (Settings epic piece 5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.audit.constants import AuditAction
from app.modules.campaigns.models import CampaignCategory
from app.modules.campaigns.schemas import (
    CampaignCategoryCreateRequest,
    CampaignCategoryUpdateRequest,
)
from app.modules.campaigns.service import CampaignCategoryService


def _make_service() -> CampaignCategoryService:
    session = AsyncMock()
    svc = CampaignCategoryService.__new__(CampaignCategoryService)
    svc._session = session
    svc._repo = AsyncMock()
    svc._audit = AsyncMock()
    return svc


def _make_category(
    *,
    name: str = "Holiday",
    description: str | None = None,
    color: str | None = None,
    category_id: uuid.UUID | None = None,
) -> CampaignCategory:
    c = MagicMock(spec=CampaignCategory)
    c.id = category_id or uuid.uuid4()
    c.name = name
    c.description = description
    c.color = color
    c.created_at = datetime.now(UTC)
    return c


@pytest.mark.asyncio
async def test_create_happy_writes_audit():
    svc = _make_service()
    actor = uuid.uuid4()
    svc._repo.get_by_name.return_value = None
    created = _make_category(name="Promo", color="#ff8800")
    svc._repo.create_category.return_value = created

    resp = await svc.create_category(
        CampaignCategoryCreateRequest(name="Promo", color="#ff8800"),
        actor_id=actor,
    )

    assert resp.name == "Promo"
    svc._repo.create_category.assert_awaited_once_with(
        name="Promo", description=None, color="#ff8800"
    )
    kwargs = svc._audit.append.await_args.kwargs
    assert kwargs["action"] == AuditAction.CREATE.value
    assert kwargs["entity_type"] == "campaign_category"
    assert kwargs["actor_id"] == actor
    assert kwargs["before_state"] is None
    assert kwargs["after_state"]["name"] == "Promo"


@pytest.mark.asyncio
async def test_create_duplicate_name_conflict():
    svc = _make_service()
    svc._repo.get_by_name.return_value = _make_category(name="Promo")
    with pytest.raises(ConflictError):
        await svc.create_category(
            CampaignCategoryCreateRequest(name="Promo"), actor_id=uuid.uuid4()
        )
    svc._repo.create_category.assert_not_awaited()
    svc._audit.append.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_color_only_diff_applied():
    svc = _make_service()
    existing = _make_category(name="Promo", color=None)
    svc._repo.get.return_value = existing
    updated = _make_category(
        category_id=existing.id, name="Promo", color="#abcdef"
    )
    svc._repo.apply_updates.return_value = updated

    resp = await svc.update_category(
        existing.id,
        CampaignCategoryUpdateRequest(color="#abcdef"),
        actor_id=uuid.uuid4(),
    )

    assert resp.color == "#abcdef"
    diff = svc._repo.apply_updates.await_args.args[1]
    assert diff == {"color": "#abcdef"}
    assert (
        svc._audit.append.await_args.kwargs["action"]
        == AuditAction.UPDATE.value
    )


@pytest.mark.asyncio
async def test_update_empty_body_no_changes():
    svc = _make_service()
    svc._repo.get.return_value = _make_category()
    with pytest.raises(ConflictError):
        await svc.update_category(
            uuid.uuid4(),
            CampaignCategoryUpdateRequest(),
            actor_id=uuid.uuid4(),
        )
    svc._repo.apply_updates.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_not_found():
    svc = _make_service()
    svc._repo.get.return_value = None
    with pytest.raises(NotFoundError):
        await svc.update_category(
            uuid.uuid4(),
            CampaignCategoryUpdateRequest(name="x"),
            actor_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_update_rename_collision():
    svc = _make_service()
    target = _make_category(name="Reactivation")
    svc._repo.get.return_value = target
    svc._repo.get_by_name.return_value = _make_category(name="Promo")
    with pytest.raises(ConflictError):
        await svc.update_category(
            target.id,
            CampaignCategoryUpdateRequest(name="Promo"),
            actor_id=uuid.uuid4(),
        )
    svc._repo.apply_updates.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_happy_writes_audit():
    svc = _make_service()
    c = _make_category(name="Promo")
    svc._repo.get.return_value = c
    svc._repo.count_campaign_links.return_value = 0

    await svc.delete_category(c.id, actor_id=uuid.uuid4())

    svc._repo.delete_category.assert_awaited_once_with(c)
    assert (
        svc._audit.append.await_args.kwargs["action"]
        == AuditAction.DELETE.value
    )


@pytest.mark.asyncio
async def test_delete_blocked_when_in_use():
    svc = _make_service()
    c = _make_category()
    svc._repo.get.return_value = c
    svc._repo.count_campaign_links.return_value = 4

    with pytest.raises(ConflictError) as exc:
        await svc.delete_category(c.id, actor_id=uuid.uuid4())
    assert exc.value.details == {"campaigns": 4}
    svc._repo.delete_category.assert_not_awaited()
    svc._audit.append.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_not_found():
    svc = _make_service()
    svc._repo.get.return_value = None
    with pytest.raises(NotFoundError):
        await svc.delete_category(uuid.uuid4(), actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_list_envelope_clamps_and_carries_usage():
    svc = _make_service()
    c1 = _make_category(name="Promo", color=None)
    c2 = _make_category(name="Welcome", color="#ff0000")
    svc._repo.list_paginated.return_value = ([(c1, 0), (c2, 3)], 2)

    resp = await svc.list_categories(q=None, limit=10000, offset=-5)

    assert resp.total == 2
    assert resp.limit == 500  # clamped to upper bound
    assert resp.offset == 0  # clamped to non-negative
    assert resp.items[1].usage_count == 3
    svc._repo.list_paginated.assert_awaited_once_with(
        q=None, limit=500, offset=0
    )
