"""Audit repository — append-only writes."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from app.db.repository import BaseRepository
from app.modules.audit.models import AuditLog


class AuditRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def append(
        self,
        *,
        actor_type: str,
        action: str,
        entity_type: str,
        actor_id: uuid.UUID | None = None,
        entity_id: uuid.UUID | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
    ) -> AuditLog:
        return await self.create(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_state=before_state,
            after_state=after_state,
        )

    def _filtered(
        self,
        stmt,
        *,
        entity_type: str | None,
        entity_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
        action: str | None,
    ):
        if entity_type:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
        if actor_id:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        return stmt

    async def list_logs(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        action: str | None = None,
    ) -> Sequence[AuditLog]:
        stmt = self._filtered(
            select(AuditLog),
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            action=action,
        )
        stmt = (
            stmt.order_by(AuditLog.created_at.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_logs(
        self,
        *,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        action: str | None = None,
    ) -> int:
        inner = self._filtered(
            select(AuditLog),
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            action=action,
        )
        stmt = sa.select(sa.func.count()).select_from(inner.subquery())
        result = await self.session.execute(stmt)
        return int(result.scalar_one())
