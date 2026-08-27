"""Unit tests for ConversationService — repositories are AsyncMocked.

Verifies that each service method enforces the state-machine guard,
writes the new state through the repo with optimistic concurrency,
appends an audit row, and emits the right domain event.

Phase 4.5 fixes covered:
- Conv-C1 (approve/reject guard)
- Conv-C2 (assert_transition before acquire_lock in assign)
- Conv-C3 (force_transition releases lock when leaving HUMAN_ASSIGNED)
- Conv-I2 (rowcount==0 raises ConcurrentModificationError)
- Conv-I5 (FIRST_ACTIVATED event after NEW→AI_ACTIVE)
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import events as events_module
from app.core.exceptions import (
    ConcurrentModificationError,
    ConflictError,
    NotFoundError,
    StateTransitionError,
    ValidationError,
)
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.conversations.service import ConversationService


def _make_conv(
    state: ConversationState,
    locked_by: uuid.UUID | None = None,
    ai_enabled: bool = True,
) -> Conversation:
    c = MagicMock(spec=Conversation)
    c.id = uuid.uuid4()
    c.contact_id = uuid.uuid4()
    c.state = state
    c.ai_enabled = ai_enabled
    c.locked_by = locked_by
    c.lock_expires_at = None
    return c


def _make_service(conv: Conversation, *, rows_affected: int = 1) -> ConversationService:
    """Build a service with mocked session/repo/audit.

    The live service signature is `ConversationService(session)`. We patch
    `_repo` and `_audit` after construction so the test controls every DB
    call deterministically.
    """
    session = AsyncMock()
    session.flush = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)
    # P0.3: approve()/reject() resolve the owning agent via
    # session.get(Contact, ...). Default to an unassigned contact so the
    # tenancy gate is a no-op for these legacy tests (rule: no assigned
    # agent → any agent may act). Per-test overrides set an owner.
    session.get = AsyncMock(
        return_value=SimpleNamespace(assigned_agent_id=None)
    )

    svc = ConversationService(session)

    repo = AsyncMock()
    repo.get.return_value = conv
    repo.get_or_404.return_value = conv
    repo.update_state.return_value = rows_affected
    repo.acquire_lock.return_value = True
    repo.release_lock.return_value = True
    repo.create_for_contact.return_value = conv

    audit = AsyncMock()
    audit.append.return_value = MagicMock()

    msg_repo = AsyncMock()
    # Default: no pending DRAFT — approve() returns None.
    msg_repo.get_latest_draft_outbound.return_value = None

    svc._repo = repo
    svc._msg_repo = msg_repo
    svc._audit = audit
    return svc


@pytest.fixture(autouse=True)
def captured_events(monkeypatch):
    events: list[tuple[str, dict]] = []

    def capture(name, **payload):
        events.append((name, payload))

    monkeypatch.setattr(events_module, "emit_event", capture)
    # service.py imports `emit_event` at module level — patch there too.
    import app.modules.conversations.service as svc_mod
    monkeypatch.setattr(svc_mod, "emit_event", capture)
    return events


@pytest.fixture(autouse=True)
def mock_ai_resume_task(monkeypatch):
    """Prevent the Celery task import inside force_transition from
    attempting to connect to Redis during unit tests."""
    mock = MagicMock()
    mock.apply_async = MagicMock(return_value=None)
    try:
        import app.modules.ai.tasks as ai_tasks
        monkeypatch.setattr(ai_tasks, "update_memory_on_ai_resume", mock)
    except Exception:
        monkeypatch.setattr(
            "app.modules.ai.tasks.update_memory_on_ai_resume",
            mock,
            raising=False,
        )
    return mock


# --------------------------------------------------- handle_inbound_message
# Conv-I5: NEW → AI_ACTIVE emits FIRST_ACTIVATED event after commit.

@pytest.mark.asyncio
async def test_inbound_creates_conversation_and_emits_first_activated(captured_events):
    new_conv = _make_conv(ConversationState.NEW)
    contact_id = uuid.uuid4()
    svc = _make_service(new_conv)

    await svc.handle_inbound_message(contact_id)

    svc._repo.create_for_contact.assert_awaited_once_with(contact_id=contact_id)
    svc._repo.update_state.assert_awaited_once()
    kw = svc._repo.update_state.await_args.kwargs
    assert kw["expected_state"] == ConversationState.NEW
    assert kw["new_state"] == ConversationState.AI_ACTIVE
    # Conv-I5: FIRST_ACTIVATED event emitted.
    assert any(name == "conversation.first_activated" or "first_activated" in name.lower()
               for name, _ in captured_events)


# ----------------------------------------------------- pause_ai / resume_ai

@pytest.mark.asyncio
async def test_pause_ai_from_ai_active():
    conv = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv)
    await svc.pause_ai(conv.id, uuid.uuid4())
    svc._repo.update_state.assert_awaited_once()
    kw = svc._repo.update_state.await_args.kwargs
    assert kw["new_state"] == ConversationState.AI_PAUSED


@pytest.mark.asyncio
async def test_resume_ai_releases_stale_lock():
    holder = uuid.uuid4()
    conv = _make_conv(ConversationState.AI_PAUSED, locked_by=holder)
    svc = _make_service(conv)
    await svc.resume_ai(conv.id, uuid.uuid4())
    svc._repo.release_lock.assert_awaited()


# -------------------------------------------------------- B1.3: Conv-C2

@pytest.mark.asyncio
async def test_assign_illegal_transition_does_not_acquire_lock():
    """Conv-C2: from CLOSED, assign() must reject before any lock side-effect."""
    closed_conv = _make_conv(ConversationState.CLOSED)
    svc = _make_service(closed_conv)

    # CLOSED is a terminal state — assert_transition raises ConflictError
    # (not StateTransitionError) per state_machine.py:106. The Conv-C2
    # invariant is the same either way: the rejection happens before any
    # lock side-effect.
    with pytest.raises((ConflictError, StateTransitionError, ValidationError)):
        await svc.assign(closed_conv.id, uuid.uuid4(), uuid.uuid4())

    svc._repo.acquire_lock.assert_not_awaited()
    svc._repo.update_state.assert_not_awaited()


# -------------------------------------------------------- B1.1: Conv-C1

@pytest.mark.asyncio
async def test_approve_rejects_non_awaiting_approval_source():
    """Conv-C1: approve() must raise when source state is not AWAITING_APPROVAL."""
    conv = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv)
    with pytest.raises(StateTransitionError, match="AWAITING_APPROVAL"):
        await svc.approve(conv.id, uuid.uuid4())
    svc._repo.update_state.assert_not_awaited()
    svc._audit.append.assert_not_awaited()


# -------------------------------------------------------- B1.2: Conv-C1

@pytest.mark.asyncio
async def test_reject_rejects_non_awaiting_approval_source():
    """Conv-C1: reject() must raise when source state is not AWAITING_APPROVAL."""
    conv = _make_conv(ConversationState.AI_PAUSED)
    svc = _make_service(conv)
    with pytest.raises(StateTransitionError, match="AWAITING_APPROVAL"):
        await svc.reject(conv.id, uuid.uuid4())
    svc._repo.update_state.assert_not_awaited()
    svc._audit.append.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_from_awaiting_approval_succeeds():
    conv = _make_conv(ConversationState.AWAITING_APPROVAL)
    svc = _make_service(conv)
    await svc.approve(conv.id, uuid.uuid4())
    svc._repo.update_state.assert_awaited_once()
    kw = svc._repo.update_state.await_args.kwargs
    assert kw["new_state"] == ConversationState.AI_ACTIVE


# -------------------------------------------------------- B-11: approve→send

@pytest.mark.asyncio
async def test_approve_promotes_latest_draft_to_queued_and_returns_id():
    """B-11: approve() promotes the latest DRAFT outbound message to QUEUED
    and returns its id so the router can dispatch the send task post-commit."""
    from app.modules.messaging.constants import MessageDeliveryStatus

    conv = _make_conv(ConversationState.AWAITING_APPROVAL)
    svc = _make_service(conv)

    draft = MagicMock()
    draft.id = uuid.uuid4()
    svc._msg_repo.get_latest_draft_outbound.return_value = draft

    returned = await svc.approve(conv.id, uuid.uuid4())

    assert returned == draft.id
    svc._msg_repo.get_latest_draft_outbound.assert_awaited_once_with(conv.id)
    svc._msg_repo.update_delivery_status.assert_awaited_once()
    args, kw = svc._msg_repo.update_delivery_status.await_args
    assert args[0] == draft.id
    assert args[1] == MessageDeliveryStatus.QUEUED
    assert kw["last_error"] is None
    # State transition still happened.
    assert svc._repo.update_state.await_args.kwargs["new_state"] == (
        ConversationState.AI_ACTIVE
    )


@pytest.mark.asyncio
async def test_approve_with_no_pending_draft_returns_none_and_no_promotion():
    """B-11: approve() with no DRAFT still transitions state but returns None
    and never touches a message — nothing is dispatched."""
    conv = _make_conv(ConversationState.AWAITING_APPROVAL)
    svc = _make_service(conv)  # default get_latest_draft_outbound → None

    returned = await svc.approve(conv.id, uuid.uuid4())

    assert returned is None
    svc._msg_repo.update_delivery_status.assert_not_awaited()
    svc._repo.update_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_wrong_state_does_not_promote_draft():
    """Conv-C1 + B-11: a bad-state approve() must not promote any draft."""
    conv = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv)
    with pytest.raises(StateTransitionError, match="AWAITING_APPROVAL"):
        await svc.approve(conv.id, uuid.uuid4())
    svc._msg_repo.get_latest_draft_outbound.assert_not_awaited()
    svc._msg_repo.update_delivery_status.assert_not_awaited()


# -------------------------------------------------------- B1.4: Conv-C3

@pytest.mark.asyncio
async def test_force_transition_from_human_assigned_releases_lock():
    """Conv-C3: leaving HUMAN_ASSIGNED must release the lock.
    Also: HUMAN_ASSIGNED → AI_ACTIVE re-enables AI and dispatches memory update."""
    holder = uuid.uuid4()
    conv = _make_conv(ConversationState.HUMAN_ASSIGNED, locked_by=holder)
    svc = _make_service(conv)

    await svc.force_transition(conv.id, ConversationState.AI_ACTIVE, uuid.uuid4())

    svc._repo.release_lock.assert_awaited()
    svc._repo.update_state.assert_awaited_once()
    assert conv.ai_enabled is True


@pytest.mark.asyncio
async def test_force_transition_to_closed_from_ai_active_does_not_release_unheld_lock():
    """Sanity: when not leaving HUMAN_ASSIGNED, release_lock should not be called."""
    conv = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv)

    await svc.force_transition(conv.id, ConversationState.CLOSED, uuid.uuid4())

    svc._repo.release_lock.assert_not_awaited()


# -------------------------------------------------------- B1.5: Conv-I2

@pytest.mark.asyncio
async def test_concurrent_transition_raises_concurrent_modification():
    """Conv-I2: rowcount==0 from update_state must raise ConcurrentModificationError."""
    conv = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv, rows_affected=0)  # simulate concurrent transition

    with pytest.raises(ConcurrentModificationError):
        await svc.pause_ai(conv.id, uuid.uuid4())

    # Audit must not be written when the state update lost the race.
    svc._audit.append.assert_not_awaited()


# -------------------------------------------------------- close

@pytest.mark.asyncio
async def test_close_releases_lock_when_held():
    holder = uuid.uuid4()
    conv = _make_conv(ConversationState.HUMAN_ASSIGNED, locked_by=holder)
    svc = _make_service(conv)
    await svc.close(conv.id, uuid.uuid4())
    svc._repo.release_lock.assert_awaited()
    svc._repo.update_state.assert_awaited_once()
    kw = svc._repo.update_state.await_args.kwargs
    assert kw["new_state"] == ConversationState.CLOSED


# ===================================================================
# P0.3 — per-conversation tenancy on override endpoints.
# Role-only gating let any agent act on any conversation. assign()
# must not steal a conversation actively locked by another agent;
# approve()/reject() are gated on the contact's assigned_agent_id
# (AWAITING_APPROVAL carries no lock). admin bypasses all of these.
# ===================================================================

from datetime import UTC, datetime, timedelta  # noqa: E402

from app.core.exceptions import PermissionError as AppPermissionError  # noqa: E402


def _locked(state, holder):
    """A conversation with an active (non-expired) lock held by `holder`.

    Uses a source state with a legal arc to HUMAN_ASSIGNED so assign()'s
    assert_transition() passes and execution reaches the P0.3 ownership
    check (HUMAN_ASSIGNED→HUMAN_ASSIGNED would be a noop ValidationError
    raised before the lock check)."""
    conv = _make_conv(state, locked_by=holder)
    conv.lock_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    return conv


@pytest.mark.asyncio
async def test_p0_3_agent_cannot_assign_conversation_locked_by_other():
    agent_b = uuid.uuid4()
    conv = _locked(ConversationState.AI_ACTIVE, agent_b)
    svc = _make_service(conv)
    with pytest.raises(AppPermissionError):
        await svc.assign(conv.id, uuid.uuid4(), uuid.uuid4(), actor_role="agent")
    svc._repo.acquire_lock.assert_not_awaited()
    svc._repo.update_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_p0_3_lock_holder_can_reassign_own_conversation():
    agent_a = uuid.uuid4()
    conv = _locked(ConversationState.AI_ACTIVE, agent_a)
    svc = _make_service(conv)
    await svc.assign(conv.id, uuid.uuid4(), agent_a, actor_role="agent")
    svc._repo.update_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_p0_3_admin_bypasses_assign_lock_ownership():
    agent_b = uuid.uuid4()
    conv = _locked(ConversationState.AI_ACTIVE, agent_b)
    svc = _make_service(conv)
    await svc.assign(conv.id, uuid.uuid4(), uuid.uuid4(), actor_role="admin")
    svc._repo.update_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_p0_3_agent_cannot_approve_other_agents_thread():
    owner = uuid.uuid4()
    conv = _make_conv(ConversationState.AWAITING_APPROVAL)
    svc = _make_service(conv)
    svc._session.get = AsyncMock(
        return_value=SimpleNamespace(assigned_agent_id=owner)
    )
    with pytest.raises(AppPermissionError):
        await svc.approve(conv.id, uuid.uuid4(), actor_role="agent")
    svc._repo.update_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_p0_3_agent_cannot_reject_other_agents_thread():
    owner = uuid.uuid4()
    conv = _make_conv(ConversationState.AWAITING_APPROVAL)
    svc = _make_service(conv)
    svc._session.get = AsyncMock(
        return_value=SimpleNamespace(assigned_agent_id=owner)
    )
    with pytest.raises(AppPermissionError):
        await svc.reject(conv.id, uuid.uuid4(), actor_role="agent")
    svc._repo.update_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_p0_3_assigned_agent_can_approve_own_thread():
    owner = uuid.uuid4()
    conv = _make_conv(ConversationState.AWAITING_APPROVAL)
    svc = _make_service(conv)
    svc._session.get = AsyncMock(
        return_value=SimpleNamespace(assigned_agent_id=owner)
    )
    await svc.approve(conv.id, owner, actor_role="agent")
    svc._repo.update_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_p0_3_admin_can_reject_any_thread():
    owner = uuid.uuid4()
    conv = _make_conv(ConversationState.AWAITING_APPROVAL)
    svc = _make_service(conv)
    svc._session.get = AsyncMock(
        return_value=SimpleNamespace(assigned_agent_id=owner)
    )
    await svc.reject(conv.id, uuid.uuid4(), actor_role="admin")
    svc._repo.update_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_p0_3_unassigned_thread_any_agent_may_approve():
    """Documented rule: no assigned agent → no owner to protect → allowed."""
    conv = _make_conv(ConversationState.AWAITING_APPROVAL)
    svc = _make_service(conv)  # default session.get → assigned_agent_id=None
    await svc.approve(conv.id, uuid.uuid4(), actor_role="agent")
    svc._repo.update_state.assert_awaited_once()


# ===================================================================
# Bulk update
# ===================================================================


def _bulk_patch(*, state=None, add_tag_ids=None, remove_tag_ids=None):
    """Build a BulkConversationPatch with the given fields."""
    from app.modules.conversations.schemas import BulkConversationPatch

    return BulkConversationPatch(
        state=state,
        add_tag_ids=add_tag_ids,
        remove_tag_ids=remove_tag_ids,
    )


@pytest.fixture
def mock_tag_repos(monkeypatch):
    """Mock TagRepository and ContactTagRepository so bulk_update passes
    tag validation and attach/detach without a real DB."""
    tag_repo = AsyncMock()
    tag_repo.get = AsyncMock(
        return_value=SimpleNamespace(id=uuid.uuid4(), name="test")
    )

    ct_repo = AsyncMock()
    ct_repo.attach = AsyncMock(return_value=None)
    ct_repo.detach = AsyncMock(return_value=None)

    mock_tag_repo_cls = MagicMock(return_value=tag_repo)
    mock_ct_repo_cls = MagicMock(return_value=ct_repo)

    monkeypatch.setattr(
        "app.modules.conversations.service.TagRepository", mock_tag_repo_cls
    )
    monkeypatch.setattr(
        "app.modules.conversations.service.ContactTagRepository", mock_ct_repo_cls
    )
    return tag_repo, ct_repo


@pytest.mark.asyncio
async def test_bulk_update_state_change(mock_tag_repos):
    conv1 = _make_conv(ConversationState.AI_ACTIVE)
    conv2 = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv1)
    svc._repo.get = AsyncMock(side_effect=[conv1, conv2])

    patch = _bulk_patch(state=ConversationState.AI_PAUSED)
    result = await svc.bulk_update(
        ids=[conv1.id, conv2.id],
        patch=patch,
        actor_id=uuid.uuid4(),
        actor_role="admin",
    )

    assert result.count == 2
    assert result.failed == []
    assert svc._repo.update_state.call_count == 2
    svc._audit.append.assert_awaited_once()


@pytest.mark.asyncio
async def test_bulk_update_partial_failure_not_found(mock_tag_repos):
    conv = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv)
    ghost = uuid.uuid4()
    svc._repo.get = AsyncMock(side_effect=lambda cid: conv if cid == conv.id else None)

    patch = _bulk_patch(state=ConversationState.AI_PAUSED)
    result = await svc.bulk_update(
        ids=[conv.id, ghost],
        patch=patch,
        actor_id=uuid.uuid4(),
        actor_role="admin",
    )

    assert result.count == 1
    assert len(result.failed) == 1
    assert result.failed[0].id == ghost
    assert result.failed[0].error == "not_found"


@pytest.mark.asyncio
async def test_bulk_update_invalid_transition_collected_as_failure(mock_tag_repos):
    """An illegal transition is caught and recorded, not raised — the
    remaining IDs continue processing."""
    conv1 = _make_conv(ConversationState.CLOSED)  # terminal
    conv2 = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv1)
    svc._repo.get = AsyncMock(side_effect=[conv1, conv2])

    patch = _bulk_patch(state=ConversationState.AI_PAUSED)
    result = await svc.bulk_update(
        ids=[conv1.id, conv2.id],
        patch=patch,
        actor_id=uuid.uuid4(),
        actor_role="admin",
    )

    assert result.count == 1
    assert len(result.failed) == 1
    assert result.failed[0].id == conv1.id
    # conv2 was still processed.
    assert svc._repo.update_state.call_count == 1


@pytest.mark.asyncio
async def test_bulk_update_add_tags(mock_tag_repos):
    conv = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv)
    tag_id = uuid.uuid4()

    patch = _bulk_patch(add_tag_ids=[tag_id])
    result = await svc.bulk_update(
        ids=[conv.id],
        patch=patch,
        actor_id=uuid.uuid4(),
        actor_role="admin",
    )

    assert result.count == 1
    assert result.failed == []
    svc._repo.update_state.assert_not_awaited()
    svc._audit.append.assert_awaited_once()
    _, ct_repo = mock_tag_repos
    ct_repo.attach.assert_awaited_once()


@pytest.mark.asyncio
async def test_bulk_update_remove_tags(mock_tag_repos):
    conv = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv)
    tag_id = uuid.uuid4()

    patch = _bulk_patch(remove_tag_ids=[tag_id])
    result = await svc.bulk_update(
        ids=[conv.id],
        patch=patch,
        actor_id=uuid.uuid4(),
        actor_role="admin",
    )

    assert result.count == 1
    assert result.failed == []
    _, ct_repo = mock_tag_repos
    ct_repo.detach.assert_awaited_once()


@pytest.mark.asyncio
async def test_bulk_update_state_and_tags_together(mock_tag_repos):
    conv = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv)
    tag_id = uuid.uuid4()

    patch = _bulk_patch(
        state=ConversationState.CLOSED,
        add_tag_ids=[tag_id],
    )
    result = await svc.bulk_update(
        ids=[conv.id],
        patch=patch,
        actor_id=uuid.uuid4(),
        actor_role="admin",
    )

    assert result.count == 1
    assert result.failed == []
    svc._repo.update_state.assert_awaited_once()
    _, ct_repo = mock_tag_repos
    ct_repo.attach.assert_awaited_once()


@pytest.mark.asyncio
async def test_bulk_update_nonexistent_tag_raises_not_found(mock_tag_repos):
    conv = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv)
    tag_repo, _ = mock_tag_repos
    tag_repo.get = AsyncMock(return_value=None)  # tag doesn't exist

    patch = _bulk_patch(add_tag_ids=[uuid.uuid4()])
    with pytest.raises(NotFoundError):
        await svc.bulk_update(
            ids=[conv.id],
            patch=patch,
            actor_id=uuid.uuid4(),
            actor_role="admin",
        )


@pytest.mark.asyncio
async def test_bulk_update_concurrent_modification_collected_as_failure(mock_tag_repos):
    conv = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv, rows_affected=0)  # simulate concurrent transition

    patch = _bulk_patch(state=ConversationState.CLOSED)
    result = await svc.bulk_update(
        ids=[conv.id],
        patch=patch,
        actor_id=uuid.uuid4(),
        actor_role="admin",
    )

    assert result.count == 0
    assert len(result.failed) == 1
    assert result.failed[0].error == "concurrent_modification"


@pytest.mark.asyncio
async def test_bulk_update_releases_lock_when_leaving_human_assigned(mock_tag_repos):
    holder = uuid.uuid4()
    conv = _make_conv(ConversationState.HUMAN_ASSIGNED, locked_by=holder)
    svc = _make_service(conv)

    patch = _bulk_patch(state=ConversationState.AI_ACTIVE)
    result = await svc.bulk_update(
        ids=[conv.id],
        patch=patch,
        actor_id=uuid.uuid4(),
        actor_role="admin",
    )

    assert result.count == 1
    svc._repo.release_lock.assert_awaited_once_with(conv.id)


@pytest.mark.asyncio
async def test_bulk_update_same_state_noop_collected_as_failure(mock_tag_repos):
    """assert_transition rejects same-state no-ops as ValidationError."""
    conv = _make_conv(ConversationState.AI_ACTIVE)
    svc = _make_service(conv)

    patch = _bulk_patch(state=ConversationState.AI_ACTIVE)
    result = await svc.bulk_update(
        ids=[conv.id],
        patch=patch,
        actor_id=uuid.uuid4(),
        actor_role="admin",
    )

    assert result.count == 0
    assert len(result.failed) == 1
    assert "noop" in result.failed[0].error.lower() or "invalid" in result.failed[0].error.lower()
