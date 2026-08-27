"""AI repository — DB access for ai_events."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select

from app.db.repository import BaseRepository
from app.modules.ai.models import AIEvent


class AIEventRepository(BaseRepository[AIEvent]):
    model = AIEvent

    async def list_by_conversation(
        self,
        conversation_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[AIEvent], int]:
        """Return (rows, total) for ai_events scoped to one conversation.

        Ordered newest-first so admins inspecting a thread see the most
        recent AI round-trips at the top of the page. Total is a real
        COUNT (not ``len(items)``) so pagination metadata is correct.
        """
        rows_stmt = (
            select(AIEvent)
            .where(AIEvent.conversation_id == conversation_id)
            .order_by(AIEvent.created_at.desc())
            .offset(max(0, offset))
            .limit(limit)
        )
        total_stmt = (
            select(func.count())
            .select_from(AIEvent)
            .where(AIEvent.conversation_id == conversation_id)
        )
        rows_result = await self.session.execute(rows_stmt)
        total_result = await self.session.execute(total_stmt)
        return rows_result.scalars().all(), int(total_result.scalar_one())

    # ------------------------------------------------------ sync counterparts
    # Used by the AI Celery tasks (DSD §4.3 — AI round-trip persistence).

    def record_event_sync(
        self,
        *,
        conversation_id: uuid.UUID,
        request: dict[str, Any],
        response: dict[str, Any],
        intent: str | None,
        confidence: float | None,
        latency_ms: int | None,
        cost_estimate: float | None,
        error: str | None,
    ) -> AIEvent:
        from sqlalchemy.orm import Session as SyncSession

        session: SyncSession = self.session  # type: ignore[assignment]
        event = AIEvent(
            conversation_id=conversation_id,
            request=request,
            response=response,
            intent=intent,
            confidence=confidence,
            latency_ms=latency_ms,
            cost_estimate=cost_estimate,
            error=error,
        )
        session.add(event)
        session.flush()
        return event
