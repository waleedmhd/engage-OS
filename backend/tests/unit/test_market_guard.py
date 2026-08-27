"""Unit tests for Phase 4 corruption guard — sub-threshold extractions
must never silently mutate trusted contact state."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.market.repository import ContactProductTagRepository


def _make_async_repo():
    session = AsyncMock()
    repo = ContactProductTagRepository(session)
    return repo, session


def _make_sync_repo(session):
    return ContactProductTagRepository(session)


# ----------------------------------------------------------------- async guard


@pytest.mark.asyncio
async def test_guard_skips_when_confidence_below_auto_min():
    """Sub-auto confidence → increment_tag returns early, zero writes."""
    repo, session = _make_async_repo()
    repo._read_auto_min = AsyncMock(return_value=0.85)

    await repo.increment_tag(
        contact_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        side="BUY",
        confidence=0.50,
    )

    # The session.execute should NOT have been called.
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_guard_allows_when_confidence_equals_auto_min():
    """Confidence exactly at auto_min → increment proceeds normally."""
    repo, session = _make_async_repo()
    repo._read_auto_min = AsyncMock(return_value=0.85)

    await repo.increment_tag(
        contact_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        side="SELL",
        confidence=0.85,
    )

    # Session execute WAS called (the ON CONFLICT upsert).
    session.execute.assert_called()


@pytest.mark.asyncio
async def test_guard_allows_when_confidence_above_auto_min():
    """High confidence → increment fires normally."""
    repo, session = _make_async_repo()
    repo._read_auto_min = AsyncMock(return_value=0.85)

    await repo.increment_tag(
        contact_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        side="BUY",
        confidence=0.95,
    )

    session.execute.assert_called()


@pytest.mark.asyncio
async def test_guard_no_confidence_backward_compat():
    """Missing confidence (None) → no guard applied, increment fires normally."""
    repo, session = _make_async_repo()

    await repo.increment_tag(
        contact_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        side="SELL",
    )
    # _read_auto_min should never be called when confidence is None.
    session.execute.assert_called()


@pytest.mark.asyncio
async def test_guard_skips_when_threshold_raised():
    """When admin raises auto_min to 0.95, 0.90 no longer clears the gate."""
    repo, session = _make_async_repo()
    repo._read_auto_min = AsyncMock(return_value=0.95)

    await repo.increment_tag(
        contact_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        side="BUY",
        confidence=0.90,
    )

    session.execute.assert_not_called()


# ---------------------------------------------------------------- sync guard


def test_guard_sync_skips_below_auto_min():
    """Sync variant: sub-auto confidence → early return."""
    from unittest.mock import MagicMock

    session = MagicMock()
    repo = _make_sync_repo(session)

    with patch(
        "app.modules.settings.repository.get_numeric_setting_sync", return_value=0.85
    ):
        repo.increment_tag_sync(
            contact_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            side="BUY",
            confidence=0.30,
        )

    # Session execute should NOT have been called.
    session.execute.assert_not_called()


def test_guard_sync_allows_above_auto_min():
    """Sync variant: high confidence → increment proceeds."""
    from unittest.mock import MagicMock

    session = MagicMock()
    repo = _make_sync_repo(session)

    with patch(
        "app.modules.settings.repository.get_numeric_setting_sync", return_value=0.85
    ):
        repo.increment_tag_sync(
            contact_id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            side="SELL",
            confidence=0.95,
        )

    session.execute.assert_called()


def test_guard_sync_no_confidence_backward_compat():
    """Sync variant: missing confidence → no guard, fires normally."""
    from unittest.mock import MagicMock

    session = MagicMock()
    repo = _make_sync_repo(session)

    repo.increment_tag_sync(
        contact_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        side="BUY",
    )

    session.execute.assert_called()
