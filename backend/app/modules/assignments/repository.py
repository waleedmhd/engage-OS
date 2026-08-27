"""Assignment repository — agent lookups for round-robin auto-assignment.

The lock state itself lives on conversations.locked_by/lock_expires_at and is
manipulated through ConversationRepository. This module owns no tables.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.conversations.models import Conversation


class AssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active_agents(self) -> list[User]:
        """Active users in roles eligible to be assigned conversations.

        Both `agent` and `admin` are eligible by default — admin is a
        superset of agent in the DSD §6.1 role model.
        """
        stmt = (
            select(User)
            .where(User.is_active.is_(True))
            .where(User.role.in_(("agent", "admin")))
            .order_by(User.id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def next_round_robin_agent(self) -> User | None:
        """Pick the next agent for round-robin assignment.

        Algorithm: among active eligible users, select the one whose most
        recent `locked_conversations` lock is oldest (or who has none). Ties
        broken by user.id for determinism. NULLS FIRST puts agents who have
        never been assigned at the head of the queue.
        """
        # Subquery: most recent assignment timestamp per user (via locked_by).
        recent = (
            select(Conversation.updated_at)
            .where(Conversation.locked_by == User.id)
            .order_by(Conversation.updated_at.desc())
            .limit(1)
            .correlate(User)
            .scalar_subquery()
        )

        stmt = (
            select(User)
            .where(User.is_active.is_(True))
            .where(User.role.in_(("agent", "admin")))
            .order_by(recent.asc().nulls_first(), User.id)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
