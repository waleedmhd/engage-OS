"""Audit service (DSD §9).

Append-only. Two access shapes:

* **Write** — most domain modules call ``AuditRepository.append`` *directly*
  inside their own service so the audit row flushes in the same transaction
  as the domain write. That pattern is unchanged and intentional.
* **Read** — the admin audit viewer (DSD §9 / §7.1) goes through
  ``AuditService(session).list_logs`` → ``AuditRepository``.

``record`` is retained for callers that want a service-mediated write
co-located with this session.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditLogResponse
from app.schemas.common import Page


def _to_response(row: AuditLog) -> AuditLogResponse:
    return AuditLogResponse(
        id=str(row.id),
        actor_type=row.actor_type,
        actor_id=str(row.actor_id) if row.actor_id is not None else None,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=str(row.entity_id) if row.entity_id is not None else None,
        before_state=row.before_state,
        after_state=row.after_state,
        created_at=row.created_at,
    )


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AuditRepository(session)

    async def list_logs(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        action: str | None = None,
    ) -> Page[AuditLogResponse]:
        rows = await self.repo.list_logs(
            page=page,
            page_size=page_size,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            action=action,
        )
        total = await self.repo.count_logs(
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            action=action,
        )
        return Page[AuditLogResponse](
            items=[_to_response(r) for r in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def record(
        self,
        *,
        actor_type: str,
        actor_id: uuid.UUID | None,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID | None,
        before_state: dict | None = None,
        after_state: dict | None = None,
    ) -> AuditLog:
        """Service-mediated audit write.

        Currently callerless: domain services write audit rows by calling
        ``AuditRepository.append`` directly so the audit insert flushes in
        the same session as the domain change (transactional co-location).
        This wrapper exists for two future uses: (a) a DSD §9 event-bus
        subscriber that writes audit rows out-of-band, and (b) any future
        write path that wants a single service entry point rather than
        bypassing into the repository. Do not introduce a wrapper-only
        layer for existing co-located writers.
        """
        return await self.repo.append(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_state=before_state,
            after_state=after_state,
        )
