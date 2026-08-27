"""Conversation repository — DB access only."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, text, update

from app.db.repository import BaseRepository
from app.modules.contacts.models import Contact
from app.modules.conversations.constants import LOCK_TIMEOUT_SECONDS, ConversationState
from app.modules.conversations.models import Conversation
from app.modules.messaging.constants import MessageDirection
from app.modules.messaging.models import Message


class ConversationRepository(BaseRepository[Conversation]):
    model = Conversation

    async def list_conversations(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        state: str | None = None,
        agent_id: uuid.UUID | None = None,
    ) -> Sequence[Conversation]:
        stmt = select(Conversation)
        if state:
            stmt = stmt.where(Conversation.state == state)
        if agent_id:
            stmt = stmt.where(Conversation.locked_by == agent_id)
        stmt = (
            stmt.order_by(Conversation.last_message_at.desc().nulls_last())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_inbox(
        self,
        *,
        state: str | None = None,
        assigned_agent_id: uuid.UUID | None = None,
        contact_id: uuid.UUID | None = None,
        tag_id: uuid.UUID | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Inbox listing with embedded contact summary + last-message preview.

        Implementation: a single SELECT joining `contacts` and a LATERAL
        subquery against `messages` for the most recent row per conversation.
        Truncation is applied in SQL (LEFT(content, 140)) so the wire payload
        stays small for large pages.

        Returns: (rows, total). Each row is a dict ready for Pydantic
        validation into ConversationListItem.
        """
        # LATERAL subquery: latest message per conversation. Wrapped as
        # subquery + .lateral() so SQLAlchemy emits the LATERAL keyword.
        last_msg_subq = (
            select(
                Message.id.label("m_id"),
                Message.direction.label("m_direction"),
                func.left(Message.content, 140).label("m_content"),
                Message.created_at.label("m_created_at"),
            )
            .where(Message.conversation_id == Conversation.id)
            .order_by(Message.created_at.desc())
            .limit(1)
            .lateral("last_msg")
        )

        # Correlated EXISTS subquery: true when there are inbound messages
        # newer than the agent's last read (or never read). Drives the
        # unread dot / bold styling in the inbox frontend.
        unread_check = (
            select(text("1"))
            .select_from(Message)
            .where(
                Message.conversation_id == Conversation.id,
                Message.direction == MessageDirection.INBOUND,
                or_(
                    Conversation.last_read_at.is_(None),
                    Message.created_at > Conversation.last_read_at,
                ),
            )
            .correlate(Conversation)
            .exists()
            .label("unread")
        )

        clauses: list[Any] = []
        if state is not None:
            states = [s.strip() for s in state.split(",") if s.strip()]
            if len(states) == 1:
                clauses.append(Conversation.state == states[0])
            else:
                clauses.append(Conversation.state.in_(states))
        if contact_id is not None:
            clauses.append(Conversation.contact_id == contact_id)
        if tag_id is not None:
            from app.modules.categorization.models import ContactTag

            clauses.append(
                Conversation.contact_id.in_(
                    select(ContactTag.contact_id).where(ContactTag.tag_id == tag_id)
                )
            )
        if assigned_agent_id is not None:
            # Match either active lock-holder or the contact's assigned agent.
            clauses.append(
                or_(
                    Conversation.locked_by == assigned_agent_id,
                    Contact.assigned_agent_id == assigned_agent_id,
                )
            )
        if q:
            pattern = f"%{q}%"
            clauses.append(
                or_(
                    Contact.name.ilike(pattern),
                    Contact.phone.ilike(pattern),
                    Contact.company.ilike(pattern),
                )
            )

        stmt = (
            select(
                Conversation.id,
                Conversation.state,
                Conversation.ai_enabled,
                Conversation.locked_by,
                Conversation.lock_expires_at,
                Conversation.last_message_at,
                unread_check,
                Contact.id.label("contact_id"),
                Contact.name.label("contact_name"),
                Contact.phone.label("contact_phone"),
                Contact.assigned_agent_id.label("contact_assigned_agent_id"),
                Contact.ai_assigned.label("contact_ai_assigned"),
                last_msg_subq.c.m_id,
                last_msg_subq.c.m_direction,
                last_msg_subq.c.m_content,
                last_msg_subq.c.m_created_at,
            )
            .join(Contact, Contact.id == Conversation.contact_id)
            .outerjoin(last_msg_subq, text("true"))
        )

        count_stmt = (
            select(func.count())
            .select_from(Conversation)
            .join(Contact, Contact.id == Conversation.contact_id)
        )

        if clauses:
            stmt = stmt.where(*clauses)
            count_stmt = count_stmt.where(*clauses)

        stmt = (
            stmt.order_by(Conversation.last_message_at.desc().nulls_last(),
                          Conversation.id.desc())
            .limit(limit)
            .offset(offset)
        )

        rows = (await self.session.execute(stmt)).all()
        total = int((await self.session.execute(count_stmt)).scalar_one())

        items: list[dict[str, Any]] = []
        for r in rows:
            last_message = None
            if r.m_id is not None:
                last_message = {
                    "id": r.m_id,
                    "direction": r.m_direction,
                    "content": r.m_content or "",
                    "created_at": r.m_created_at,
                }
            items.append(
                {
                    "id": r.id,
                    "state": r.state,
                    "ai_enabled": r.ai_enabled,
                    "locked_by": r.locked_by,
                    "lock_expires_at": r.lock_expires_at,
                    "last_message_at": r.last_message_at,
                    "unread": bool(r.unread),
                    "contact": {
                        "id": r.contact_id,
                        "name": r.contact_name,
                        "phone": r.contact_phone,
                        "assigned_agent_id": r.contact_assigned_agent_id,
                        "ai_assigned": bool(r.contact_ai_assigned),
                    },
                    "last_message": last_message,
                }
            )

        # Attach each contact's resolved tag chips (id/name/color) via a single
        # follow-up query so the inbox can render tags without an N+1 per row and
        # without fanning out the main LATERAL join. Done after pagination so we
        # only fetch tags for the contacts actually on this page.
        from app.modules.categorization.models import ContactTag, Tag

        for item in items:
            item["tags"] = []
        contact_ids = [item["contact"]["id"] for item in items]
        if contact_ids:
            tag_rows = (
                await self.session.execute(
                    select(
                        ContactTag.contact_id,
                        Tag.id,
                        Tag.name,
                        Tag.color,
                    )
                    .join(Tag, Tag.id == ContactTag.tag_id)
                    .where(ContactTag.contact_id.in_(contact_ids))
                    .order_by(Tag.name)
                )
            ).all()
            by_contact: dict[Any, list[dict[str, Any]]] = {}
            for tr in tag_rows:
                by_contact.setdefault(tr.contact_id, []).append(
                    {"id": tr.id, "name": tr.name, "color": tr.color}
                )
            for item in items:
                item["tags"] = by_contact.get(item["contact"]["id"], [])
        return items, total

    async def count_needs_human(self) -> dict[str, int]:
        """Count conversations needing human intervention by state.

        Returns a dict with counts for AWAITING_APPROVAL and HUMAN_ASSIGNED.
        """
        cnt_label = func.count().label("cnt")
        stmt = (
            select(Conversation.state, cnt_label)
            .where(
                Conversation.state.in_(
                    [ConversationState.AWAITING_APPROVAL.value, ConversationState.HUMAN_ASSIGNED.value]
                )
            )
            .group_by(Conversation.state)
        )
        rows = (await self.session.execute(stmt)).all()
        by_state: dict[str, int] = {}
        for row in rows:
            by_state[row.state] = int(row.cnt or 0)
        return {
            "awaiting_approval": by_state.get(ConversationState.AWAITING_APPROVAL.value, 0),
            "human_assigned": by_state.get(ConversationState.HUMAN_ASSIGNED.value, 0),
            "total": sum(by_state.values()),
        }

    async def create_for_contact(self, *, contact_id: uuid.UUID) -> Conversation:
        """Create a new NEW-state conversation for a contact."""
        return await self.create(contact_id=contact_id)

    async def get_open_for_contact(self, contact_id: uuid.UUID) -> Conversation | None:
        stmt = (
            select(Conversation)
            .where(Conversation.contact_id == contact_id)
            .where(Conversation.state != ConversationState.CLOSED.value)
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_state(
        self,
        *,
        conversation_id: uuid.UUID,
        expected_state: ConversationState | str,
        new_state: ConversationState | str,
    ) -> int:
        """Conv-I2: optimistic UPDATE.

        Returns the number of rows affected. A return of 0 means another
        transaction transitioned the conversation between the caller's read
        and this write — the caller should raise ConcurrentModificationError.
        """
        expected = expected_state.value if hasattr(expected_state, "value") else expected_state
        new = new_state.value if hasattr(new_state, "value") else new_state
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.state == expected)
            .values(state=new)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0  # type: ignore[attr-defined]

    async def acquire_lock(
        self,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        ttl_seconds: int = LOCK_TIMEOUT_SECONDS,
    ) -> bool:
        """Atomically acquire/extend the conversation lock.

        Succeeds when:
        - the lock is unheld, or
        - the lock is expired, or
        - the lock is already held by `agent_id` (renewal).
        """
        now = datetime.now(UTC)
        new_expiry = now + timedelta(seconds=ttl_seconds)
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .where(
                or_(
                    Conversation.locked_by.is_(None),
                    Conversation.lock_expires_at < now,
                    Conversation.locked_by == agent_id,
                )
            )
            .values(locked_by=agent_id, lock_expires_at=new_expiry)
            .returning(Conversation.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def release_lock(
        self,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID | None = None,
    ) -> bool:
        """Clear locked_by / lock_expires_at on a conversation.

        If *agent_id* is provided the UPDATE is gated on
        ``locked_by = :agent_id`` — a no-op if another agent holds the
        lock.  Pass ``agent_id=None`` (default) for an unconditional
        release, which is the correct behaviour for administrative
        operations (force_transition, close, resume_ai clearing a stale
        lock) where ownership is not a prerequisite.
        """
        where_clauses = [Conversation.id == conversation_id]
        if agent_id is not None:
            where_clauses.append(Conversation.locked_by == agent_id)
        stmt = (
            update(Conversation)
            .where(*where_clauses)
            .values(locked_by=None, lock_expires_at=None)
            .returning(Conversation.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def touch_last_message(
        self, conversation_id: uuid.UUID, when: datetime
    ) -> None:
        await self.update(conversation_id, last_message_at=when)

    async def touch_last_read(
        self, conversation_id: uuid.UUID, when: datetime
    ) -> None:
        """Mark a conversation as read by the agent (sets last_read_at)."""
        await self.update(conversation_id, last_read_at=when)

    # ------------------------------------------------------ sync counterparts
    # Used by Celery tasks that operate with a synchronous session.

    def get_active_for_contact_sync(
        self, contact_id: uuid.UUID
    ) -> Conversation | None:
        """Sync mirror of get_open_for_contact for Celery tasks."""
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        stmt = (
            select(Conversation)
            .where(Conversation.contact_id == contact_id)
            .where(Conversation.state != ConversationState.CLOSED.value)
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        return session.execute(stmt).scalar_one_or_none()

    def create_for_contact_sync(
        self, *, contact_id: uuid.UUID
    ) -> Conversation:
        """Sync conversation creation for Celery tasks. Default state = NEW."""
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        conv = Conversation(contact_id=contact_id)
        session.add(conv)
        session.flush()
        session.refresh(conv)
        return conv

    def touch_last_message_sync(
        self, conversation_id: uuid.UUID, when: datetime
    ) -> None:
        """Sync mirror of touch_last_message for Celery tasks.

        Bumps last_message_at so the inbox (ordered by last_message_at DESC)
        floats the conversation to the top after an outbound message — the
        WhatsApp-style reorder. Caller commits.
        """
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(last_message_at=when)
        )

    def update_outreach_state_sync(
        self,
        conversation_id: uuid.UUID,
        new_state: str,
        *,
        expected_state: str | None = None,
    ) -> int:
        """Set the outreach_state column (engagement policy §5).

        When *expected_state* is provided, the UPDATE is guarded: zero rows are
        affected if the current outreach_state differs (optimistic concurrency).
        Returns rowcount.
        """
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(outreach_state=new_state)
        )
        if expected_state is not None:
            stmt = stmt.where(Conversation.outreach_state == expected_state)
        result = session.execute(stmt)
        return result.rowcount or 0  # type: ignore[attr-defined]

    def update_state_sync(
        self,
        *,
        conversation_id: uuid.UUID,
        expected_state: ConversationState | str,
        new_state: ConversationState | str,
    ) -> int:
        """Sync mirror of update_state with Conv-I2 optimistic concurrency.

        Returns rowcount. Caller raises ConcurrentModificationError on 0.
        """
        from sqlalchemy.orm import Session as SyncSession
        session: SyncSession = self.session  # type: ignore[assignment]
        expected = expected_state.value if hasattr(expected_state, "value") else expected_state
        new = new_state.value if hasattr(new_state, "value") else new_state
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.state == expected)
            .values(state=new)
        )
        result = session.execute(stmt)
        session.flush()
        return result.rowcount or 0  # type: ignore[attr-defined]
