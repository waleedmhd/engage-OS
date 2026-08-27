"""Categorization repository — tags, contact_tags, tag_suggestions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.repository import BaseRepository
from app.modules.categorization.constants import TagSuggestionStatus
from app.modules.categorization.models import ContactTag, Tag, TagSuggestion


class TagRepository(BaseRepository[Tag]):
    model = Tag

    async def get_by_name(self, name: str) -> Tag | None:
        stmt = select(Tag).where(Tag.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[Tag]:
        result = await self.session.execute(select(Tag).order_by(Tag.name.asc()))
        return result.scalars().all()

    async def list_paginated(
        self,
        *,
        q: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[Tag, int]], int]:
        usage_subq = (
            sa.select(sa.func.count(ContactTag.contact_id))
            .where(ContactTag.tag_id == Tag.id)
            .correlate(Tag)
            .scalar_subquery()
        )

        base = sa.select(Tag, usage_subq.label("usage_count"))
        count_base = sa.select(sa.func.count(Tag.id))
        if q:
            like = f"%{q}%"
            base = base.where(Tag.name.ilike(like))
            count_base = count_base.where(Tag.name.ilike(like))

        page_stmt = base.order_by(Tag.name.asc()).offset(offset).limit(limit)
        rows = (await self.session.execute(page_stmt)).all()
        items: list[tuple[Tag, int]] = [(r[0], int(r[1])) for r in rows]
        total = int((await self.session.execute(count_base)).scalar_one())
        return items, total

    async def create_tag(
        self, *, name: str, description: str | None, color: str | None
    ) -> Tag:
        tag = Tag(name=name, description=description, color=color)
        self.session.add(tag)
        await self.session.flush()
        await self.session.refresh(tag)
        return tag

    async def apply_updates(self, tag: Tag, diff: dict) -> Tag:
        for k, v in diff.items():
            setattr(tag, k, v)
        await self.session.flush()
        await self.session.refresh(tag)
        return tag

    async def delete_tag(self, tag: Tag) -> None:
        await self.session.delete(tag)
        await self.session.flush()

    async def count_contact_links(self, tag_id: uuid.UUID) -> int:
        stmt = (
            sa.select(sa.func.count())
            .select_from(ContactTag)
            .where(ContactTag.tag_id == tag_id)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_pending_suggestions(self, tag_id: uuid.UUID) -> int:
        stmt = (
            sa.select(sa.func.count())
            .select_from(TagSuggestion)
            .where(
                TagSuggestion.tag_id == tag_id,
                TagSuggestion.status == TagSuggestionStatus.PENDING.value,
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())


class TagSuggestionRepository(BaseRepository[TagSuggestion]):
    model = TagSuggestion

    async def list_pending(
        self, *, page: int = 1, page_size: int = 50
    ) -> Sequence[TagSuggestion]:
        stmt = (
            select(TagSuggestion)
            .where(TagSuggestion.status == TagSuggestionStatus.PENDING.value)
            .order_by(TagSuggestion.created_at.asc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_filtered(
        self,
        *,
        status: str | None = None,
        contact_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[Sequence[TagSuggestion], int]:
        """Return (rows, total) for the filtered + paginated query.

        Filters:
          - status: exact match against TagSuggestion.status. Caller is
            responsible for validating against TagSuggestionStatus.
          - contact_id: exact match.

        Ordering: oldest pending first (created_at ASC) so reviewers work
        through the backlog FIFO.
        """
        base = select(TagSuggestion)
        if status is not None:
            base = base.where(TagSuggestion.status == status)
        if contact_id is not None:
            base = base.where(TagSuggestion.contact_id == contact_id)

        count_stmt = sa.select(sa.func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        page_stmt = (
            base.order_by(TagSuggestion.created_at.asc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        rows = (await self.session.execute(page_stmt)).scalars().all()
        return rows, total

    async def review(
        self,
        suggestion_id: uuid.UUID,
        *,
        status: str,
        reviewer_id: uuid.UUID,
    ) -> TagSuggestion | None:
        return await self.update(
            suggestion_id,
            status=status,
            reviewed_by=reviewer_id,
            reviewed_at=datetime.now(UTC),
        )


class ContactTagRepository:
    """Composite-PK link table — does not extend BaseRepository."""

    def __init__(self, session) -> None:
        self.session = session

    async def attach(
        self,
        *,
        contact_id: uuid.UUID,
        tag_id: uuid.UUID,
        approver_id: uuid.UUID | None = None,
    ) -> None:
        stmt = (
            pg_insert(ContactTag)
            .values(
                contact_id=contact_id,
                tag_id=tag_id,
                approved_by=approver_id,
                approved_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(constraint="pk_contact_tags")
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def detach(self, *, contact_id: uuid.UUID, tag_id: uuid.UUID) -> None:
        from sqlalchemy import and_, delete

        stmt = delete(ContactTag).where(
            and_(ContactTag.contact_id == contact_id, ContactTag.tag_id == tag_id)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def list_for_contact(self, contact_id: uuid.UUID) -> Sequence[ContactTag]:
        stmt = select(ContactTag).where(ContactTag.contact_id == contact_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()
