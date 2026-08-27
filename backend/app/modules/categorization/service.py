"""Categorization service (DSD §4.6).

Two execution paths share this class:

1. **Sync (Celery / AI orchestrator)** — `create_suggestion_sync` is a
   staticmethod called from `AIOrchestrator._decide` against a sync session.
   It upserts the Tag and inserts a PENDING TagSuggestion. Unchanged.

2. **Async (HTTP)** — instance methods backed by the async repositories.
   The router layer instantiates `CategorizationService(session)`, calls
   methods, and commits the unit of work after returning.

Approve/reject side-effects are transactionally co-located with the audit
write so a failure mid-flow rolls back both the status change and the audit
row, matching the audit module's documented expectation.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession

from app.core.exceptions import ConflictError, NotFoundError, StateTransitionError
from app.modules.audit.constants import ActorType, AuditAction
from app.modules.audit.repository import AuditRepository
from app.modules.categorization.constants import TagSuggestionStatus
from app.modules.categorization.models import ContactTag, Tag, TagSuggestion
from app.modules.categorization.repository import (
    ContactTagRepository,
    TagRepository,
    TagSuggestionRepository,
)
from app.modules.categorization.schemas import (
    TagCreateRequest,
    TagListResponse,
    TagResponse,
    TagUpdateRequest,
    TagWithUsageResponse,
)


class CategorizationService:
    """Async service for the human-review API and the sync helper for the
    AI orchestrator's Celery task.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tags = TagRepository(session)
        self._suggestions = TagSuggestionRepository(session)
        self._contact_tags = ContactTagRepository(session)
        self._audit = AuditRepository(session)

    # -------------------------------------------------------- sync (Celery)

    @staticmethod
    def create_suggestion_sync(
        session: SyncSession,
        *,
        contact_id: uuid.UUID,
        tag_name: str,
        confidence: float | None,
        reason: str | None = None,
    ) -> TagSuggestion:
        """Look up (or upsert) the tag, then persist a PENDING suggestion.

        Uses INSERT ... ON CONFLICT DO NOTHING for the Tag row so concurrent
        tasks that suggest the same tag name simultaneously do not raise a
        UniqueConstraintError. After the upsert, the tag is loaded by name.
        """
        tag_insert = (
            pg_insert(Tag)
            .values(name=tag_name)
            .on_conflict_do_nothing(index_elements=["name"])
        )
        session.execute(tag_insert)
        session.flush()

        tag = session.execute(
            sa.select(Tag).where(Tag.name == tag_name)
        ).scalar_one()

        suggestion = TagSuggestion(
            contact_id=contact_id,
            tag_id=tag.id,
            confidence=confidence,
            reason=reason,
            status=TagSuggestionStatus.PENDING.value,
        )
        session.add(suggestion)
        session.flush()
        return suggestion

    # -------------------------------------------------------- async (HTTP)

    async def list_tags(self) -> Sequence[Tag]:
        return await self._tags.list_all()

    # ---------------------------------------------------------- tag CRUD

    async def list_tags_paginated(
        self,
        *,
        q: str | None,
        limit: int,
        offset: int,
    ) -> TagListResponse:
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        rows, total = await self._tags.list_paginated(
            q=q, limit=limit, offset=offset
        )
        items = [
            TagWithUsageResponse.model_validate(
                {
                    **TagResponse.model_validate(tag).model_dump(),
                    "usage_count": usage,
                }
            )
            for tag, usage in rows
        ]
        return TagListResponse(
            items=items, total=total, limit=limit, offset=offset
        )

    async def create_tag(
        self,
        payload: TagCreateRequest,
        *,
        actor_id: uuid.UUID,
    ) -> TagResponse:
        existing = await self._tags.get_by_name(payload.name)
        if existing is not None:
            raise ConflictError("tag_name_taken")

        tag = await self._tags.create_tag(
            name=payload.name,
            description=payload.description,
            color=payload.color,
        )
        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action=AuditAction.CREATE.value,
            entity_type="tag",
            entity_id=tag.id,
            before_state=None,
            after_state={
                "name": tag.name,
                "description": tag.description,
                "color": tag.color,
            },
        )
        return TagResponse.model_validate(tag)

    async def update_tag(
        self,
        tag_id: uuid.UUID,
        payload: TagUpdateRequest,
        *,
        actor_id: uuid.UUID,
    ) -> TagResponse:
        tag = await self._tags.get(tag_id)
        if tag is None:
            raise NotFoundError(f"Tag:{tag_id}")

        proposed = payload.model_dump(exclude_unset=True)
        diff = {k: v for k, v in proposed.items() if getattr(tag, k) != v}
        if not diff:
            raise ConflictError("no_changes")

        if "name" in diff:
            taken = await self._tags.get_by_name(diff["name"])
            if taken is not None and taken.id != tag.id:
                raise ConflictError("tag_name_taken")

        before = {
            "name": tag.name,
            "description": tag.description,
            "color": tag.color,
        }
        updated = await self._tags.apply_updates(tag, diff)
        after = {
            "name": updated.name,
            "description": updated.description,
            "color": updated.color,
        }
        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action=AuditAction.UPDATE.value,
            entity_type="tag",
            entity_id=updated.id,
            before_state=before,
            after_state=after,
        )
        return TagResponse.model_validate(updated)

    async def delete_tag(
        self,
        tag_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
    ) -> None:
        tag = await self._tags.get(tag_id)
        if tag is None:
            raise NotFoundError(f"Tag:{tag_id}")

        contacts = await self._tags.count_contact_links(tag_id)
        suggestions = await self._tags.count_pending_suggestions(tag_id)
        if contacts > 0 or suggestions > 0:
            raise ConflictError(
                "tag_in_use",
                details={"contacts": contacts, "suggestions": suggestions},
            )

        snapshot = {
            "name": tag.name,
            "description": tag.description,
            "color": tag.color,
        }
        await self._tags.delete_tag(tag)
        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action=AuditAction.DELETE.value,
            entity_type="tag",
            entity_id=tag_id,
            before_state=snapshot,
            after_state=None,
        )

    async def list_contact_tags(
        self, contact_id: uuid.UUID
    ) -> Sequence[ContactTag]:
        return await self._contact_tags.list_for_contact(contact_id)

    async def apply_tag(
        self,
        contact_id: uuid.UUID,
        tag_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
    ) -> None:
        """Manually attach a saved tag to a contact (no AI suggestion needed).

        Idempotent: the composite-PK insert uses ON CONFLICT DO NOTHING, so
        re-applying an already-present tag is harmless. Mirrors the approve
        flow's audit co-location.
        """
        tag = await self._tags.get(tag_id)
        if tag is None:
            raise NotFoundError(f"Tag:{tag_id}")

        await self._contact_tags.attach(
            contact_id=contact_id,
            tag_id=tag_id,
            approver_id=actor_id,
        )
        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action="contact.tag_applied",
            entity_type="contact",
            entity_id=contact_id,
            before_state=None,
            after_state={"tag_id": str(tag_id), "tag_name": tag.name},
        )

    async def remove_tag(
        self,
        contact_id: uuid.UUID,
        tag_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
    ) -> None:
        """Manually detach a tag from a contact. Idempotent: detaching a tag
        that is not present is a no-op (no error)."""
        await self._contact_tags.detach(contact_id=contact_id, tag_id=tag_id)
        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=actor_id,
            action="contact.tag_removed",
            entity_type="contact",
            entity_id=contact_id,
            before_state={"tag_id": str(tag_id)},
            after_state=None,
        )

    async def list_suggestions(
        self,
        *,
        status: str | None,
        contact_id: uuid.UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[Sequence[TagSuggestion], int]:
        # Default to PENDING when caller did not specify a status — reviewers
        # almost always want the inbox view.
        effective_status = (
            status if status is not None else TagSuggestionStatus.PENDING.value
        )
        return await self._suggestions.list_filtered(
            status=effective_status,
            contact_id=contact_id,
            page=page,
            page_size=page_size,
        )

    async def approve(
        self,
        suggestion_id: uuid.UUID,
        *,
        reviewer_id: uuid.UUID,
        note: str | None = None,
    ) -> TagSuggestion:
        suggestion = await self._review(
            suggestion_id,
            reviewer_id=reviewer_id,
            new_status=TagSuggestionStatus.APPROVED,
            audit_action=AuditAction.APPROVE.value,
            note=note,
        )
        # Persist the actual ContactTag assignment. Idempotent: composite PK
        # with ON CONFLICT DO NOTHING means a re-run with a manual prior link
        # is harmless.
        await self._contact_tags.attach(
            contact_id=suggestion.contact_id,
            tag_id=suggestion.tag_id,
            approver_id=reviewer_id,
        )
        return suggestion

    async def reject(
        self,
        suggestion_id: uuid.UUID,
        *,
        reviewer_id: uuid.UUID,
        note: str | None = None,
    ) -> TagSuggestion:
        return await self._review(
            suggestion_id,
            reviewer_id=reviewer_id,
            new_status=TagSuggestionStatus.REJECTED,
            audit_action=AuditAction.REJECT.value,
            note=note,
        )

    # ------------------------------------------------------------ internals

    async def _review(
        self,
        suggestion_id: uuid.UUID,
        *,
        reviewer_id: uuid.UUID,
        new_status: TagSuggestionStatus,
        audit_action: str,
        note: str | None,
    ) -> TagSuggestion:
        """Shared approve/reject pipeline: load → guard → update → audit."""
        suggestion = await self._suggestions.get(suggestion_id)
        if suggestion is None:
            raise NotFoundError(f"TagSuggestion:{suggestion_id}")

        if suggestion.status != TagSuggestionStatus.PENDING.value:
            # Idempotency: a previously reviewed suggestion cannot be reviewed
            # again. Returns 409 via the global exception handler.
            raise StateTransitionError(
                f"only pending suggestions can be {new_status.value}",
                details={"current_status": suggestion.status},
            )

        before_state = {
            "status": suggestion.status,
            "reviewed_by": None,
            "reviewed_at": None,
        }

        updated = await self._suggestions.review(
            suggestion_id,
            status=new_status.value,
            reviewer_id=reviewer_id,
        )
        # We just verified the row exists above, and review() updates that
        # same row through the identity map, so a None here would indicate a
        # concurrent delete — surface as NotFound rather than crash.
        if updated is None:
            raise NotFoundError(f"TagSuggestion:{suggestion_id}")

        after_state: dict = {
            "status": updated.status,
            "reviewed_by": str(reviewer_id),
            "reviewed_at": (
                updated.reviewed_at.isoformat() if updated.reviewed_at else None
            ),
        }
        if note is not None:
            after_state["note"] = note

        await self._audit.append(
            actor_type=ActorType.USER.value,
            actor_id=reviewer_id,
            action=audit_action,
            entity_type="TagSuggestion",
            entity_id=suggestion_id,
            before_state=before_state,
            after_state=after_state,
        )
        return updated
