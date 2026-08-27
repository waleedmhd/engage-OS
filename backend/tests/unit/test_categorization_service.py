"""Unit tests for CategorizationService — repositories are AsyncMocked.

Covers the human-review pipeline (approve/reject) and the listing helpers.
The sync `create_suggestion_sync` path is exercised by `test_ai_decide.py`
against a real session; we don't duplicate that here.

Invariants verified:
  - approve()  : updates status, attaches ContactTag, records audit.
  - reject()   : updates status, records audit, NO ContactTag insertion.
  - both       : raise StateTransitionError when source status != PENDING.
  - both       : raise NotFoundError when the suggestion is missing.
  - listing    : delegates filters/pagination to the repository.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ConflictError, NotFoundError, StateTransitionError
from app.modules.audit.constants import ActorType, AuditAction
from app.modules.categorization.constants import TagSuggestionStatus
from app.modules.categorization.models import Tag, TagSuggestion
from app.modules.categorization.schemas import (
    TagCreateRequest,
    TagUpdateRequest,
)
from app.modules.categorization.service import CategorizationService

# ------------------------------------------------------------------ helpers


def _make_suggestion(
    *,
    status: str = TagSuggestionStatus.PENDING.value,
    suggestion_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    tag_id: uuid.UUID | None = None,
    reviewed_at: datetime | None = None,
) -> TagSuggestion:
    s = MagicMock(spec=TagSuggestion)
    s.id = suggestion_id or uuid.uuid4()
    s.contact_id = contact_id or uuid.uuid4()
    s.tag_id = tag_id or uuid.uuid4()
    s.status = status
    s.confidence = 0.9
    s.reason = "buyer_intent"
    s.reviewed_by = None
    s.reviewed_at = reviewed_at
    s.created_at = datetime.now(UTC)
    return s


def _make_service() -> CategorizationService:
    """Construct a service with all repositories replaced by AsyncMocks."""
    session = AsyncMock()
    svc = CategorizationService(session)
    svc._tags = AsyncMock()
    svc._suggestions = AsyncMock()
    svc._contact_tags = AsyncMock()
    svc._audit = AsyncMock()
    return svc


# ----------------------------------------------------------------- approve


@pytest.mark.asyncio
async def test_approve_happy_path():
    pending = _make_suggestion()
    approved = _make_suggestion(
        status=TagSuggestionStatus.APPROVED.value,
        suggestion_id=pending.id,
        contact_id=pending.contact_id,
        tag_id=pending.tag_id,
        reviewed_at=datetime.now(UTC),
    )

    svc = _make_service()
    svc._suggestions.get.return_value = pending
    svc._suggestions.review.return_value = approved

    reviewer_id = uuid.uuid4()
    result = await svc.approve(pending.id, reviewer_id=reviewer_id, note="looks good")

    # Status transition went through the repo with the right kwargs.
    svc._suggestions.review.assert_awaited_once_with(
        pending.id,
        status=TagSuggestionStatus.APPROVED.value,
        reviewer_id=reviewer_id,
    )

    # ContactTag link was created.
    svc._contact_tags.attach.assert_awaited_once_with(
        contact_id=pending.contact_id,
        tag_id=pending.tag_id,
        approver_id=reviewer_id,
    )

    # Audit row recorded with USER actor and APPROVE action, and the note
    # is captured in after_state.
    svc._audit.append.assert_awaited_once()
    audit_kwargs = svc._audit.append.await_args.kwargs
    assert audit_kwargs["actor_type"] == ActorType.USER.value
    assert audit_kwargs["actor_id"] == reviewer_id
    assert audit_kwargs["action"] == AuditAction.APPROVE.value
    assert audit_kwargs["entity_type"] == "TagSuggestion"
    assert audit_kwargs["entity_id"] == pending.id
    assert audit_kwargs["before_state"]["status"] == TagSuggestionStatus.PENDING.value
    assert audit_kwargs["after_state"]["status"] == TagSuggestionStatus.APPROVED.value
    assert audit_kwargs["after_state"]["note"] == "looks good"

    assert result is approved


@pytest.mark.asyncio
async def test_approve_idempotency_rejects_already_approved():
    already = _make_suggestion(status=TagSuggestionStatus.APPROVED.value)
    svc = _make_service()
    svc._suggestions.get.return_value = already

    with pytest.raises(StateTransitionError) as exc_info:
        await svc.approve(already.id, reviewer_id=uuid.uuid4())

    # No side effects on a guarded path.
    svc._suggestions.review.assert_not_awaited()
    svc._contact_tags.attach.assert_not_awaited()
    svc._audit.append.assert_not_awaited()
    assert exc_info.value.details.get("current_status") == TagSuggestionStatus.APPROVED.value


@pytest.mark.asyncio
async def test_approve_idempotency_rejects_already_rejected():
    already = _make_suggestion(status=TagSuggestionStatus.REJECTED.value)
    svc = _make_service()
    svc._suggestions.get.return_value = already

    with pytest.raises(StateTransitionError):
        await svc.approve(already.id, reviewer_id=uuid.uuid4())

    svc._suggestions.review.assert_not_awaited()
    svc._contact_tags.attach.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_missing_suggestion_raises_not_found():
    svc = _make_service()
    svc._suggestions.get.return_value = None

    with pytest.raises(NotFoundError):
        await svc.approve(uuid.uuid4(), reviewer_id=uuid.uuid4())

    svc._suggestions.review.assert_not_awaited()
    svc._contact_tags.attach.assert_not_awaited()
    svc._audit.append.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_without_note_omits_note_in_audit():
    pending = _make_suggestion()
    approved = _make_suggestion(
        status=TagSuggestionStatus.APPROVED.value,
        suggestion_id=pending.id,
        contact_id=pending.contact_id,
        tag_id=pending.tag_id,
        reviewed_at=datetime.now(UTC),
    )
    svc = _make_service()
    svc._suggestions.get.return_value = pending
    svc._suggestions.review.return_value = approved

    await svc.approve(pending.id, reviewer_id=uuid.uuid4())

    audit_kwargs = svc._audit.append.await_args.kwargs
    assert "note" not in audit_kwargs["after_state"]


# ------------------------------------------------------------------ reject


@pytest.mark.asyncio
async def test_reject_happy_path():
    pending = _make_suggestion()
    rejected = _make_suggestion(
        status=TagSuggestionStatus.REJECTED.value,
        suggestion_id=pending.id,
        contact_id=pending.contact_id,
        tag_id=pending.tag_id,
        reviewed_at=datetime.now(UTC),
    )

    svc = _make_service()
    svc._suggestions.get.return_value = pending
    svc._suggestions.review.return_value = rejected

    reviewer_id = uuid.uuid4()
    result = await svc.reject(pending.id, reviewer_id=reviewer_id, note="off-topic")

    svc._suggestions.review.assert_awaited_once_with(
        pending.id,
        status=TagSuggestionStatus.REJECTED.value,
        reviewer_id=reviewer_id,
    )

    # Crucially: rejection does NOT create a ContactTag.
    svc._contact_tags.attach.assert_not_awaited()

    audit_kwargs = svc._audit.append.await_args.kwargs
    assert audit_kwargs["action"] == AuditAction.REJECT.value
    assert audit_kwargs["after_state"]["status"] == TagSuggestionStatus.REJECTED.value
    assert audit_kwargs["after_state"]["note"] == "off-topic"

    assert result is rejected


@pytest.mark.asyncio
async def test_reject_rejects_non_pending_source():
    already = _make_suggestion(status=TagSuggestionStatus.APPROVED.value)
    svc = _make_service()
    svc._suggestions.get.return_value = already

    with pytest.raises(StateTransitionError):
        await svc.reject(already.id, reviewer_id=uuid.uuid4())

    svc._suggestions.review.assert_not_awaited()
    svc._audit.append.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_missing_suggestion_raises_not_found():
    svc = _make_service()
    svc._suggestions.get.return_value = None

    with pytest.raises(NotFoundError):
        await svc.reject(uuid.uuid4(), reviewer_id=uuid.uuid4())


# --------------------------------------------------------------- list APIs


@pytest.mark.asyncio
async def test_list_suggestions_defaults_to_pending():
    svc = _make_service()
    svc._suggestions.list_filtered.return_value = ([], 0)

    await svc.list_suggestions(status=None, contact_id=None, page=1, page_size=50)

    kwargs = svc._suggestions.list_filtered.await_args.kwargs
    assert kwargs["status"] == TagSuggestionStatus.PENDING.value
    assert kwargs["contact_id"] is None
    assert kwargs["page"] == 1
    assert kwargs["page_size"] == 50


@pytest.mark.asyncio
async def test_list_suggestions_passes_through_explicit_filters():
    svc = _make_service()
    svc._suggestions.list_filtered.return_value = ([], 0)
    contact_id = uuid.uuid4()

    await svc.list_suggestions(
        status=TagSuggestionStatus.APPROVED.value,
        contact_id=contact_id,
        page=3,
        page_size=10,
    )

    kwargs = svc._suggestions.list_filtered.await_args.kwargs
    assert kwargs["status"] == TagSuggestionStatus.APPROVED.value
    assert kwargs["contact_id"] == contact_id
    assert kwargs["page"] == 3
    assert kwargs["page_size"] == 10


@pytest.mark.asyncio
async def test_list_tags_delegates_to_repo():
    svc = _make_service()
    svc._tags.list_all.return_value = ["t1", "t2"]

    result = await svc.list_tags()

    svc._tags.list_all.assert_awaited_once()
    assert result == ["t1", "t2"]


@pytest.mark.asyncio
async def test_list_contact_tags_delegates_to_repo():
    svc = _make_service()
    contact_id = uuid.uuid4()
    svc._contact_tags.list_for_contact.return_value = ["link1"]

    result = await svc.list_contact_tags(contact_id)

    svc._contact_tags.list_for_contact.assert_awaited_once_with(contact_id)
    assert result == ["link1"]


# ------------------------------------------------- manual apply / remove tag


@pytest.mark.asyncio
async def test_apply_tag_attaches_and_audits():
    svc = _make_service()
    contact_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    tag = MagicMock(spec=Tag)
    tag.id = uuid.uuid4()
    tag.name = "VIP"
    svc._tags.get.return_value = tag

    await svc.apply_tag(contact_id, tag.id, actor_id=actor_id)

    # The link is created with the actor as the approver (idempotent insert).
    svc._contact_tags.attach.assert_awaited_once_with(
        contact_id=contact_id,
        tag_id=tag.id,
        approver_id=actor_id,
    )
    # Audited as a manual application by a USER actor.
    svc._audit.append.assert_awaited_once()
    kwargs = svc._audit.append.await_args.kwargs
    assert kwargs["actor_type"] == ActorType.USER.value
    assert kwargs["actor_id"] == actor_id
    assert kwargs["action"] == "contact.tag_applied"
    assert kwargs["entity_type"] == "contact"
    assert kwargs["entity_id"] == contact_id
    assert kwargs["after_state"]["tag_id"] == str(tag.id)


@pytest.mark.asyncio
async def test_apply_tag_unknown_tag_raises_not_found():
    svc = _make_service()
    svc._tags.get.return_value = None

    with pytest.raises(NotFoundError):
        await svc.apply_tag(uuid.uuid4(), uuid.uuid4(), actor_id=uuid.uuid4())

    # No link or audit row written on the guarded path.
    svc._contact_tags.attach.assert_not_awaited()
    svc._audit.append.assert_not_awaited()


@pytest.mark.asyncio
async def test_remove_tag_detaches_and_audits():
    svc = _make_service()
    contact_id = uuid.uuid4()
    tag_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    await svc.remove_tag(contact_id, tag_id, actor_id=actor_id)

    svc._contact_tags.detach.assert_awaited_once_with(
        contact_id=contact_id, tag_id=tag_id
    )
    kwargs = svc._audit.append.await_args.kwargs
    assert kwargs["action"] == "contact.tag_removed"
    assert kwargs["entity_type"] == "contact"
    assert kwargs["entity_id"] == contact_id
    assert kwargs["before_state"]["tag_id"] == str(tag_id)


# ----------------------------------------------------------------- tag CRUD


def _make_tag(
    *,
    name: str = "vip",
    description: str | None = None,
    color: str | None = None,
    tag_id: uuid.UUID | None = None,
) -> Tag:
    t = MagicMock(spec=Tag)
    t.id = tag_id or uuid.uuid4()
    t.name = name
    t.description = description
    t.color = color
    t.created_at = datetime.now(UTC)
    return t


@pytest.mark.asyncio
async def test_create_tag_happy_path_writes_audit():
    svc = _make_service()
    actor = uuid.uuid4()
    svc._tags.get_by_name.return_value = None
    created = _make_tag(name="vip", color="#ff8800")
    svc._tags.create_tag.return_value = created

    resp = await svc.create_tag(
        TagCreateRequest(name="vip", description=None, color="#ff8800"),
        actor_id=actor,
    )

    assert resp.name == "vip"
    assert resp.color == "#ff8800"
    svc._tags.create_tag.assert_awaited_once_with(
        name="vip", description=None, color="#ff8800"
    )
    svc._audit.append.assert_awaited_once()
    kwargs = svc._audit.append.await_args.kwargs
    assert kwargs["action"] == AuditAction.CREATE.value
    assert kwargs["entity_type"] == "tag"
    assert kwargs["actor_id"] == actor


@pytest.mark.asyncio
async def test_create_tag_duplicate_name_raises_conflict():
    svc = _make_service()
    svc._tags.get_by_name.return_value = _make_tag(name="vip")
    with pytest.raises(ConflictError):
        await svc.create_tag(TagCreateRequest(name="vip"), actor_id=uuid.uuid4())
    svc._tags.create_tag.assert_not_awaited()
    svc._audit.append.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_tag_color_only_diff_applied():
    svc = _make_service()
    existing = _make_tag(name="vip", color=None)
    svc._tags.get.return_value = existing
    updated = _make_tag(
        tag_id=existing.id, name="vip", color="#abcdef"
    )
    svc._tags.apply_updates.return_value = updated

    resp = await svc.update_tag(
        existing.id,
        TagUpdateRequest(color="#abcdef"),
        actor_id=uuid.uuid4(),
    )

    assert resp.color == "#abcdef"
    svc._tags.apply_updates.assert_awaited_once()
    diff = svc._tags.apply_updates.await_args.args[1]
    assert diff == {"color": "#abcdef"}
    svc._audit.append.assert_awaited_once()
    assert (
        svc._audit.append.await_args.kwargs["action"]
        == AuditAction.UPDATE.value
    )


@pytest.mark.asyncio
async def test_update_tag_empty_body_raises_no_changes():
    svc = _make_service()
    svc._tags.get.return_value = _make_tag()
    with pytest.raises(ConflictError):
        await svc.update_tag(
            uuid.uuid4(), TagUpdateRequest(), actor_id=uuid.uuid4()
        )
    svc._tags.apply_updates.assert_not_awaited()
    svc._audit.append.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_tag_not_found_raises():
    svc = _make_service()
    svc._tags.get.return_value = None
    with pytest.raises(NotFoundError):
        await svc.update_tag(
            uuid.uuid4(),
            TagUpdateRequest(name="x"),
            actor_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_update_tag_rename_collision_conflict():
    svc = _make_service()
    target = _make_tag(name="lead")
    svc._tags.get.return_value = target
    svc._tags.get_by_name.return_value = _make_tag(name="vip")  # other row
    with pytest.raises(ConflictError):
        await svc.update_tag(
            target.id, TagUpdateRequest(name="vip"), actor_id=uuid.uuid4()
        )
    svc._tags.apply_updates.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_tag_happy_writes_audit():
    svc = _make_service()
    t = _make_tag(name="vip")
    svc._tags.get.return_value = t
    svc._tags.count_contact_links.return_value = 0
    svc._tags.count_pending_suggestions.return_value = 0

    await svc.delete_tag(t.id, actor_id=uuid.uuid4())

    svc._tags.delete_tag.assert_awaited_once_with(t)
    svc._audit.append.assert_awaited_once()
    assert (
        svc._audit.append.await_args.kwargs["action"]
        == AuditAction.DELETE.value
    )


@pytest.mark.asyncio
async def test_delete_tag_blocked_when_in_use_by_contacts():
    svc = _make_service()
    t = _make_tag()
    svc._tags.get.return_value = t
    svc._tags.count_contact_links.return_value = 3
    svc._tags.count_pending_suggestions.return_value = 0

    with pytest.raises(ConflictError) as exc:
        await svc.delete_tag(t.id, actor_id=uuid.uuid4())
    assert exc.value.details == {"contacts": 3, "suggestions": 0}
    svc._tags.delete_tag.assert_not_awaited()
    svc._audit.append.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_tag_blocked_when_pending_suggestions_exist():
    svc = _make_service()
    t = _make_tag()
    svc._tags.get.return_value = t
    svc._tags.count_contact_links.return_value = 0
    svc._tags.count_pending_suggestions.return_value = 2

    with pytest.raises(ConflictError) as exc:
        await svc.delete_tag(t.id, actor_id=uuid.uuid4())
    assert exc.value.details == {"contacts": 0, "suggestions": 2}


@pytest.mark.asyncio
async def test_delete_tag_not_found_raises():
    svc = _make_service()
    svc._tags.get.return_value = None
    with pytest.raises(NotFoundError):
        await svc.delete_tag(uuid.uuid4(), actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_list_tags_paginated_envelope():
    svc = _make_service()
    t1 = _make_tag(name="lead", color=None)
    t2 = _make_tag(name="vip", color="#ff0000")
    svc._tags.list_paginated.return_value = ([(t1, 0), (t2, 5)], 2)

    resp = await svc.list_tags_paginated(q=None, limit=50, offset=0)

    assert resp.total == 2
    assert resp.limit == 50
    assert resp.offset == 0
    by_name = {it.name: it.usage_count for it in resp.items}
    assert by_name == {"lead": 0, "vip": 5}


@pytest.mark.asyncio
async def test_list_tags_paginated_clamps_limit():
    svc = _make_service()
    svc._tags.list_paginated.return_value = ([], 0)
    await svc.list_tags_paginated(q=None, limit=10_000, offset=-5)
    kwargs = svc._tags.list_paginated.await_args.kwargs
    assert kwargs["limit"] == 500
    assert kwargs["offset"] == 0
