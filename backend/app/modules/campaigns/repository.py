"""Campaign repository — DB access only.

Async methods are used by the service / FastAPI handlers; sync mirrors are
used by Celery tasks via sync_session_factory().
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session as SyncSession

from app.db.repository import BaseRepository
from app.modules.campaigns.constants import (
    CampaignRecipientStatus,
    CampaignStatus,
    CampaignType,
)
from app.modules.campaigns.models import Campaign, CampaignCategory, CampaignRecipient
from app.modules.categorization.models import ContactTag
from app.modules.contacts.constants import ContactStatus
from app.modules.contacts.models import Contact


class CampaignRepository(BaseRepository[Campaign]):
    model = Campaign

    async def list_campaigns(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
    ) -> tuple[Sequence[Campaign], int]:
        clauses: list[Any] = []
        if status == "running":
            clauses.append(
                Campaign.status.in_(
                    [CampaignStatus.QUEUED.value, CampaignStatus.DISPATCHING.value]
                )
            )
        elif status:
            clauses.append(Campaign.status == status)

        stmt = select(Campaign)
        count_stmt = select(func.count()).select_from(Campaign)
        if clauses:
            stmt = stmt.where(*clauses)
            count_stmt = count_stmt.where(*clauses)

        stmt = (
            stmt.order_by(Campaign.created_at.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total

    async def update_status(
        self, campaign_id: uuid.UUID, status: str
    ) -> Campaign | None:
        return await self.update(campaign_id, status=status)

    async def select_audience_contact_ids(
        self,
        *,
        filter_payload: dict[str, Any],
    ) -> list[uuid.UUID]:
        """Resolve an audience filter into a list of eligible contact IDs.

        Always excludes blocked contacts and marketing_opt_out=True. Tag
        filtering uses the contact_tags M2M table.
        """
        clauses: list[Any] = [
            Contact.status != ContactStatus.BLOCKED.value,
            Contact.marketing_opt_out.is_(False),
        ]

        tags = filter_payload.get("tags") or []
        if tags:
            tag_uuids = [uuid.UUID(t) if isinstance(t, str) else t for t in tags]
            clauses.append(
                Contact.id.in_(
                    sa.select(ContactTag.contact_id).where(
                        ContactTag.tag_id.in_(tag_uuids)
                    )
                )
            )

        statuses = filter_payload.get("status") or []
        if statuses:
            # Allow filtering by ACTIVE/INACTIVE explicitly (BLOCKED is always excluded above).
            clauses.append(Contact.status.in_(statuses))

        agent_id = filter_payload.get("assigned_agent_id")
        if agent_id is not None:
            clauses.append(
                Contact.assigned_agent_id
                == (uuid.UUID(agent_id) if isinstance(agent_id, str) else agent_id)
            )

        last_after = filter_payload.get("last_interaction_after")
        if last_after is not None:
            if isinstance(last_after, str):
                last_after = datetime.fromisoformat(last_after)
            clauses.append(Contact.last_interaction_at >= last_after)

        last_before = filter_payload.get("last_interaction_before")
        if last_before is not None:
            if isinstance(last_before, str):
                last_before = datetime.fromisoformat(last_before)
            clauses.append(Contact.last_interaction_at <= last_before)

        contact_ids = filter_payload.get("contact_ids") or []
        if contact_ids:
            clauses.append(
                Contact.id.in_(
                    [uuid.UUID(c) if isinstance(c, str) else c for c in contact_ids]
                )
            )

        stmt = sa.select(Contact.id).where(and_(*clauses))
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]

    async def increment_counters(
        self,
        campaign_id: uuid.UUID,
        *,
        sent_delta: int = 0,
        delivered_delta: int = 0,
        failed_delta: int = 0,
        response_delta: int = 0,
    ) -> None:
        values: dict[str, Any] = {}
        if sent_delta:
            values["sent_count"] = Campaign.sent_count + sent_delta
        if delivered_delta:
            values["delivered_count"] = Campaign.delivered_count + delivered_delta
        if failed_delta:
            values["failed_count"] = Campaign.failed_count + failed_delta
        if response_delta:
            values["response_count"] = Campaign.response_count + response_delta
        if not values:
            return
        await self.session.execute(
            update(Campaign).where(Campaign.id == campaign_id).values(**values)
        )

    async def find_due_for_scheduler(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[Campaign]:
        """Return SCHEDULED campaigns whose scheduled_at or next_run_at has passed.

        Used by the beat-driven scheduler tick. SCHEDULED one-shot campaigns
        use scheduled_at; RECURRING campaigns use next_run_at.
        """
        ts = now or datetime.now(UTC)
        due_clause = or_(
            and_(
                Campaign.type == CampaignType.SCHEDULED.value,
                Campaign.scheduled_at.is_not(None),
                Campaign.scheduled_at <= ts,
            ),
            and_(
                Campaign.type == CampaignType.RECURRING.value,
                Campaign.next_run_at.is_not(None),
                Campaign.next_run_at <= ts,
            ),
        )
        stmt = (
            select(Campaign)
            .where(Campaign.status == CampaignStatus.SCHEDULED.value)
            .where(due_clause)
            .order_by(Campaign.scheduled_at.asc().nullslast(), Campaign.next_run_at.asc().nullslast())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # ------------------------------------------------------- sync counterparts
    # Used by Celery tasks operating with sync sessions.

    def get_sync(self, campaign_id: uuid.UUID) -> Campaign | None:
        session: SyncSession = self.session  # type: ignore[assignment]
        return session.get(Campaign, campaign_id)

    def update_status_sync(
        self,
        campaign_id: uuid.UUID,
        status: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> int:
        session: SyncSession = self.session  # type: ignore[assignment]
        values: dict[str, Any] = {"status": status}
        if extra:
            values.update(extra)
        result = session.execute(
            update(Campaign).where(Campaign.id == campaign_id).values(**values)
        )
        return result.rowcount or 0  # type: ignore[attr-defined]

    def increment_counters_sync(
        self,
        campaign_id: uuid.UUID,
        *,
        sent_delta: int = 0,
        delivered_delta: int = 0,
        failed_delta: int = 0,
        response_delta: int = 0,
    ) -> None:
        session: SyncSession = self.session  # type: ignore[assignment]
        values: dict[str, Any] = {}
        if sent_delta:
            values["sent_count"] = Campaign.sent_count + sent_delta
        if delivered_delta:
            values["delivered_count"] = Campaign.delivered_count + delivered_delta
        if failed_delta:
            values["failed_count"] = Campaign.failed_count + failed_delta
        if response_delta:
            values["response_count"] = Campaign.response_count + response_delta
        if not values:
            return
        session.execute(
            update(Campaign).where(Campaign.id == campaign_id).values(**values)
        )

    def find_due_for_scheduler_sync(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[Campaign]:
        session: SyncSession = self.session  # type: ignore[assignment]
        ts = now or datetime.now(UTC)
        due_clause = or_(
            and_(
                Campaign.type == CampaignType.SCHEDULED.value,
                Campaign.scheduled_at.is_not(None),
                Campaign.scheduled_at <= ts,
            ),
            and_(
                Campaign.type == CampaignType.RECURRING.value,
                Campaign.next_run_at.is_not(None),
                Campaign.next_run_at <= ts,
            ),
        )
        stmt = (
            select(Campaign)
            .where(Campaign.status == CampaignStatus.SCHEDULED.value)
            .where(due_clause)
            .order_by(Campaign.scheduled_at.asc().nullslast(), Campaign.next_run_at.asc().nullslast())
            .limit(limit)
        )
        return list(session.execute(stmt).scalars().all())


class CampaignRecipientRepository(BaseRepository[CampaignRecipient]):
    model = CampaignRecipient

    async def list_for_campaign(
        self,
        campaign_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 100,
        status: str | None = None,
    ) -> tuple[Sequence[CampaignRecipient], int]:
        clauses: list[Any] = [CampaignRecipient.campaign_id == campaign_id]
        if status:
            clauses.append(CampaignRecipient.status == status)

        stmt = select(CampaignRecipient).where(*clauses)
        count_stmt = (
            select(func.count()).select_from(CampaignRecipient).where(*clauses)
        )
        stmt = (
            stmt.order_by(CampaignRecipient.created_at.asc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total

    async def bulk_insert(
        self, campaign_id: uuid.UUID, contact_ids: list[uuid.UUID]
    ) -> int:
        if not contact_ids:
            return 0
        rows = [
            {"campaign_id": campaign_id, "contact_id": cid} for cid in contact_ids
        ]
        stmt = (
            pg_insert(CampaignRecipient)
            .values(rows)
            .on_conflict_do_nothing(
                constraint="uq_campaign_recipients_campaign_contact"
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0  # type: ignore[attr-defined]

    async def count_by_status(self, campaign_id: uuid.UUID) -> dict[str, int]:
        stmt = (
            select(CampaignRecipient.status, func.count(CampaignRecipient.id))
            .where(CampaignRecipient.campaign_id == campaign_id)
            .group_by(CampaignRecipient.status)
        )
        result = await self.session.execute(stmt)
        return {row[0]: int(row[1]) for row in result.all()}

    async def mark_status(
        self,
        recipient_id: uuid.UUID,
        status: str,
        *,
        error: str | None = None,
    ) -> CampaignRecipient | None:
        fields: dict = {"status": status}
        if error is not None:
            fields["error_message"] = error
        return await self.update(recipient_id, **fields)

    async def cancel_pending(self, campaign_id: uuid.UUID) -> int:
        """Mark every PENDING recipient as FAILED with a cancellation reason.
        Used by cancel_campaign so the per-status counts close out correctly.
        """
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(CampaignRecipient)
            .where(
                and_(
                    CampaignRecipient.campaign_id == campaign_id,
                    CampaignRecipient.status == CampaignRecipientStatus.PENDING.value,
                )
            )
            .values(
                status=CampaignRecipientStatus.FAILED.value,
                failed_at=now,
                error_message="campaign_cancelled",
            )
        )
        return result.rowcount or 0  # type: ignore[attr-defined]

    async def error_breakdown(
        self, campaign_id: uuid.UUID
    ) -> list[tuple[str, int | None, int]]:
        stmt = (
            select(
                CampaignRecipient.error_message,
                CampaignRecipient.error_code,
                func.count(CampaignRecipient.id).label("cnt"),
            )
            .where(
                and_(
                    CampaignRecipient.campaign_id == campaign_id,
                    CampaignRecipient.status == CampaignRecipientStatus.FAILED.value,
                    CampaignRecipient.error_message.is_not(None),
                )
            )
            .group_by(CampaignRecipient.error_message, CampaignRecipient.error_code)
            .order_by(func.count(CampaignRecipient.id).desc())
            .limit(10)
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1], int(row[2])) for row in result.all()]

    # ------------------------------------------------------- sync counterparts

    def list_pending_ids_sync(
        self,
        campaign_id: uuid.UUID,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[uuid.UUID]:
        session: SyncSession = self.session  # type: ignore[assignment]
        stmt = (
            select(CampaignRecipient.id)
            .where(
                and_(
                    CampaignRecipient.campaign_id == campaign_id,
                    CampaignRecipient.status == CampaignRecipientStatus.PENDING.value,
                )
            )
            .order_by(CampaignRecipient.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return [row[0] for row in session.execute(stmt).all()]

    def get_with_contact_sync(
        self, recipient_id: uuid.UUID
    ) -> tuple[CampaignRecipient, Contact] | None:
        session: SyncSession = self.session  # type: ignore[assignment]
        stmt = (
            select(CampaignRecipient, Contact)
            .join(Contact, Contact.id == CampaignRecipient.contact_id)
            .where(CampaignRecipient.id == recipient_id)
        )
        row = session.execute(stmt).first()
        return (row[0], row[1]) if row else None

    def mark_sent_sync(
        self,
        recipient_id: uuid.UUID,
        *,
        message_id: uuid.UUID,
        meta_message_id: str | None,
    ) -> None:
        session: SyncSession = self.session  # type: ignore[assignment]
        session.execute(
            update(CampaignRecipient)
            .where(CampaignRecipient.id == recipient_id)
            .values(
                status=CampaignRecipientStatus.SENT.value,
                sent_at=datetime.now(UTC),
                message_id=message_id,
                meta_message_id=meta_message_id,
                attempt_count=CampaignRecipient.attempt_count + 1,
                error_message=None,
                error_code=None,
            )
        )

    def mark_failed_sync(
        self,
        recipient_id: uuid.UUID,
        *,
        error: str,
        error_code: int | None = None,
    ) -> None:
        session: SyncSession = self.session  # type: ignore[assignment]
        values: dict[str, Any] = {
            "status": CampaignRecipientStatus.FAILED.value,
            "failed_at": datetime.now(UTC),
            "attempt_count": CampaignRecipient.attempt_count + 1,
            "error_message": error[:500],
            "error_code": error_code,
        }
        session.execute(
            update(CampaignRecipient)
            .where(CampaignRecipient.id == recipient_id)
            .values(**values)
        )

    def count_by_status_sync(self, campaign_id: uuid.UUID) -> dict[str, int]:
        session: SyncSession = self.session  # type: ignore[assignment]
        stmt = (
            select(CampaignRecipient.status, func.count(CampaignRecipient.id))
            .where(CampaignRecipient.campaign_id == campaign_id)
            .group_by(CampaignRecipient.status)
        )
        return {row[0]: int(row[1]) for row in session.execute(stmt).all()}

    def update_delivery_status_sync(
        self,
        *,
        meta_message_id: str,
        new_status: str,
        error_code: int | None = None,
        error_message: str | None = None,
    ) -> CampaignRecipient | None:
        """Used by the messaging webhook hook to flow Meta delivery updates
        into campaign_recipient. Returns the row that was updated, or None
        if no recipient is linked to this Meta message ID.
        """
        session: SyncSession = self.session  # type: ignore[assignment]
        recipient = session.execute(
            select(CampaignRecipient).where(
                CampaignRecipient.meta_message_id == meta_message_id
            )
        ).scalar_one_or_none()
        if recipient is None:
            return None

        values: dict[str, Any] = {"status": new_status}
        now = datetime.now(UTC)
        if new_status == CampaignRecipientStatus.DELIVERED.value:
            values["delivered_at"] = now
            values["error_code"] = None
            values["error_message"] = None
        elif new_status == CampaignRecipientStatus.FAILED.value:
            values["failed_at"] = now
            if error_code is not None:
                values["error_code"] = error_code
            if error_message is not None:
                values["error_message"] = error_message[:500]

        session.execute(
            update(CampaignRecipient)
            .where(CampaignRecipient.id == recipient.id)
            .values(**values)
        )
        return recipient

    def mark_responded_for_contact_sync(
        self,
        contact_id: uuid.UUID,
        *,
        since: datetime,
    ) -> int:
        """Mark recipient.responded=True for any recent send to this contact.

        Called when an inbound message lands. `since` bounds the search so
        a reply months later doesn't get attributed to an old campaign.
        Returns the number of rows updated.
        """
        session: SyncSession = self.session  # type: ignore[assignment]
        result = session.execute(
            update(CampaignRecipient)
            .where(
                and_(
                    CampaignRecipient.contact_id == contact_id,
                    CampaignRecipient.responded.is_(False),
                    CampaignRecipient.sent_at.is_not(None),
                    CampaignRecipient.sent_at >= since,
                )
            )
            .values(responded=True)
        )
        return result.rowcount or 0  # type: ignore[attr-defined]

    def error_breakdown_sync(
        self, campaign_id: uuid.UUID
    ) -> list[tuple[str, int | None, int]]:
        session: SyncSession = self.session  # type: ignore[assignment]
        stmt = (
            select(
                CampaignRecipient.error_message,
                CampaignRecipient.error_code,
                func.count(CampaignRecipient.id).label("cnt"),
            )
            .where(
                and_(
                    CampaignRecipient.campaign_id == campaign_id,
                    CampaignRecipient.status == CampaignRecipientStatus.FAILED.value,
                    CampaignRecipient.error_message.is_not(None),
                )
            )
            .group_by(CampaignRecipient.error_message, CampaignRecipient.error_code)
            .order_by(func.count(CampaignRecipient.id).desc())
            .limit(10)
        )
        return [(row[0], row[1], int(row[2])) for row in session.execute(stmt).all()]


class CampaignCategoryRepository(BaseRepository[CampaignCategory]):
    model = CampaignCategory

    async def get_by_name(self, name: str) -> CampaignCategory | None:
        stmt = select(CampaignCategory).where(CampaignCategory.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        q: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[CampaignCategory, int]], int]:
        usage_subq = (
            sa.select(sa.func.count(Campaign.id))
            .where(Campaign.category_id == CampaignCategory.id)
            .correlate(CampaignCategory)
            .scalar_subquery()
        )

        base = sa.select(CampaignCategory, usage_subq.label("usage_count"))
        count_base = sa.select(sa.func.count(CampaignCategory.id))
        if q:
            like = f"%{q}%"
            base = base.where(CampaignCategory.name.ilike(like))
            count_base = count_base.where(CampaignCategory.name.ilike(like))

        page_stmt = base.order_by(CampaignCategory.name.asc()).offset(offset).limit(limit)
        rows = (await self.session.execute(page_stmt)).all()
        items: list[tuple[CampaignCategory, int]] = [(r[0], int(r[1])) for r in rows]
        total = int((await self.session.execute(count_base)).scalar_one())
        return items, total

    async def create_category(
        self, *, name: str, description: str | None, color: str | None
    ) -> CampaignCategory:
        category = CampaignCategory(name=name, description=description, color=color)
        self.session.add(category)
        await self.session.flush()
        await self.session.refresh(category)
        return category

    async def apply_updates(
        self, category: CampaignCategory, diff: dict
    ) -> CampaignCategory:
        for k, v in diff.items():
            setattr(category, k, v)
        await self.session.flush()
        await self.session.refresh(category)
        return category

    async def delete_category(self, category: CampaignCategory) -> None:
        await self.session.delete(category)
        await self.session.flush()

    async def count_campaign_links(self, category_id: uuid.UUID) -> int:
        stmt = (
            sa.select(sa.func.count())
            .select_from(Campaign)
            .where(Campaign.category_id == category_id)
        )
        return int((await self.session.execute(stmt)).scalar_one())
