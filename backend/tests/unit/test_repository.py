"""Unit tests for BaseRepository — covers DB-C3 identity-map staleness fix.

The DB-C3 bug: BaseRepository.update used UPDATE...RETURNING which bypassed
SQLAlchemy's identity map. Any other reference to the same row already
loaded in the session would retain its pre-update state for the lifetime of
the UoW, causing silent wrong reads.

This test creates a row, holds a reference, calls update(), and verifies
the held reference reflects the new value (proving the identity map was
not bypassed).
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.repository import BaseRepository


class _IsolatedBase(DeclarativeBase):
    """Isolated declarative base — keeps the widget table out of the app
    metadata so create_all() can run cleanly against in-memory SQLite."""


class _Widget(_IsolatedBase):
    __tablename__ = "_test_widgets_dbc3"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(sa.String(64))
    value: Mapped[int] = mapped_column(sa.Integer, default=0)


class _WidgetRepo(BaseRepository[_Widget]):
    model = _Widget


@pytest.fixture
async def widget_session() -> AsyncSession:
    """In-memory SQLite session for the widget table only."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(_IsolatedBase.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_update_does_not_leave_stale_identity_map_entry(widget_session):
    """DB-C3: after update(), references already loaded in the session must
    reflect the new value. Previously update used UPDATE...RETURNING which
    bypassed the identity map, leaving any held reference with stale state.
    """
    repo = _WidgetRepo(widget_session)

    # Create + commit a row.
    created = await repo.create(name="alpha", value=1)
    widget_id = created.id
    await widget_session.commit()

    # Load the row again (held reference).
    held = await repo.get(widget_id)
    assert held is not None
    assert held.name == "alpha"

    # Update via the repo.
    await repo.update(widget_id, name="beta", value=42)

    # Critical: the previously-held reference must reflect the update.
    # Under the buggy implementation `held.name` would still be "alpha".
    assert held.name == "beta"
    assert held.value == 42


@pytest.mark.asyncio
async def test_update_empty_kwargs_is_noop_returns_instance(widget_session):
    """DB-M15: empty kwargs returns the unchanged instance, not None."""
    repo = _WidgetRepo(widget_session)
    created = await repo.create(name="alpha", value=1)
    await widget_session.commit()

    result = await repo.update(created.id)  # no kwargs
    assert result is not None
    assert result.name == "alpha"


@pytest.mark.asyncio
async def test_update_missing_row_returns_none(widget_session):
    """DB-M15: missing row returns None (the only None case)."""
    repo = _WidgetRepo(widget_session)
    result = await repo.update(uuid.uuid4(), name="ghost")
    assert result is None
