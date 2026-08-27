"""Unit tests for `assignments.tasks.expire_stale_locks_task`.

The task uses a sync SQLAlchemy session via `sync_session_factory`. We mock
the factory to yield a `MagicMock(spec=Session)` whose `execute` calls are
scripted to mimic:

  1. The bulk SELECT FOR UPDATE SKIP LOCKED returning the expired rows.
  2. Per-row conditional UPDATE returning the conversation_id (success)
     or None (raced, skipped).

This keeps tests pure-logic — no DB required — consistent with the
project's test setup (`tests/conftest.py` ships no DB fixture).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

# Ensure every model class is registered with the SQLAlchemy mapper before
# the task module references `Conversation.id` (which triggers mapper
# configuration). Without this, importing tasks.py fails because
# Conversation.contact -> Contact resolves lazily.
from app.db import import_all_models

import_all_models()


# ---------------------------------------------------------------------- helpers


def _make_session(select_rows, update_returns):
    """Build a MagicMock session whose `execute` returns prescripted results.

    `select_rows`   — list of (conversation_id, locked_by) tuples returned
                       from the bulk SELECT (its `.all()`).
    `update_returns` — list of values returned by per-row UPDATE
                       `.scalar_one_or_none()` calls, in order. Use None
                       to simulate a raced row.
    """
    session = MagicMock(name="SyncSession")

    select_result = MagicMock(name="SelectResult")
    select_result.all.return_value = list(select_rows)

    update_results = []
    for ret in update_returns:
        r = MagicMock(name="UpdateResult")
        r.scalar_one_or_none.return_value = ret
        update_results.append(r)

    # The task calls execute() once for the SELECT, then once per row for
    # the UPDATE. Return them in order via side_effect.
    session.execute.side_effect = [select_result, *update_results]
    return session


@pytest.fixture
def patch_session(monkeypatch):
    """Patch sync_session_factory inside the tasks module to yield our mock."""
    from app.modules.assignments import tasks as tasks_module

    holder = {}

    def install(session):
        holder["session"] = session

        @contextmanager
        def fake_factory():
            yield session

        monkeypatch.setattr(tasks_module, "sync_session_factory", fake_factory)

    return install


@pytest.fixture
def captured_events(monkeypatch):
    """Capture `emit_event` calls inside the tasks module."""
    from app.modules.assignments import tasks as tasks_module

    captured: list[tuple[str, dict]] = []

    def fake_emit(event_name, **payload):
        captured.append((event_name, payload))

    monkeypatch.setattr(tasks_module, "emit_event", fake_emit)
    return captured


# ------------------------------------------------------------------------ tests


def test_releases_expired_locks_and_returns_count(patch_session, captured_events):
    """Happy path: 2 expired rows → 2 UPDATEs succeed → released=2."""
    from app.modules.assignments.tasks import expire_stale_locks_task

    conv_a, conv_b = uuid.uuid4(), uuid.uuid4()
    holder_a, holder_b = uuid.uuid4(), uuid.uuid4()

    session = _make_session(
        select_rows=[(conv_a, holder_a), (conv_b, holder_b)],
        update_returns=[conv_a, conv_b],  # both UPDATEs succeed
    )
    patch_session(session)

    result = expire_stale_locks_task()

    assert result == {"scanned": 2, "released": 2}
    # Two audit rows added (one per release).
    assert session.add.call_count == 2
    # Commit at end of task.
    assert session.commit.call_count == 1


def test_emits_audit_row_per_release(patch_session, captured_events):
    """Each released lock writes exactly one AuditLog row with system actor."""
    from app.modules.assignments.tasks import expire_stale_locks_task
    from app.modules.audit.constants import ActorType
    from app.modules.audit.models import AuditLog

    conv = uuid.uuid4()
    holder = uuid.uuid4()

    session = _make_session(
        select_rows=[(conv, holder)],
        update_returns=[conv],
    )
    patch_session(session)

    expire_stale_locks_task()

    assert session.add.call_count == 1
    audit_obj = session.add.call_args.args[0]
    assert isinstance(audit_obj, AuditLog)
    assert audit_obj.actor_type == ActorType.SYSTEM.value
    assert audit_obj.actor_id is None
    assert audit_obj.action == "conversation.lock_expired"
    assert audit_obj.entity_type == "conversation"
    assert audit_obj.entity_id == conv
    assert audit_obj.before_state == {"locked_by": str(holder)}
    assert audit_obj.after_state == {"locked_by": None}


def test_emits_domain_event_per_release(patch_session, captured_events):
    """Each release fires a `conversation.lock_expired` domain event."""
    from app.core.events import ConversationEvents
    from app.modules.assignments.tasks import expire_stale_locks_task

    conv = uuid.uuid4()
    holder = uuid.uuid4()

    session = _make_session(
        select_rows=[(conv, holder)],
        update_returns=[conv],
    )
    patch_session(session)

    expire_stale_locks_task()

    assert len(captured_events) == 1
    name, payload = captured_events[0]
    assert name == ConversationEvents.LOCK_EXPIRED
    assert payload == {
        "conversation_id": str(conv),
        "previous_holder_id": str(holder),
    }


def test_idempotent_when_no_expired_locks(patch_session, captured_events):
    """Empty SELECT result → no audit rows, no events, scanned=released=0."""
    from app.modules.assignments.tasks import expire_stale_locks_task

    session = _make_session(select_rows=[], update_returns=[])
    patch_session(session)

    result = expire_stale_locks_task()

    assert result == {"scanned": 0, "released": 0}
    assert session.add.call_count == 0
    assert captured_events == []
    # Even with zero work the task commits — cheap and keeps the txn shape
    # symmetric. Don't make this part of the contract too strict; just
    # check it doesn't crash.
    assert session.commit.call_count == 1


def test_skips_audit_when_update_loses_race(patch_session, captured_events):
    """If the conditional UPDATE matches zero rows (raced), no audit/event."""
    from app.modules.assignments.tasks import expire_stale_locks_task

    conv_a, conv_b = uuid.uuid4(), uuid.uuid4()
    holder_a, holder_b = uuid.uuid4(), uuid.uuid4()

    session = _make_session(
        select_rows=[(conv_a, holder_a), (conv_b, holder_b)],
        update_returns=[None, conv_b],  # first raced, second succeeds
    )
    patch_session(session)

    result = expire_stale_locks_task()

    assert result == {"scanned": 2, "released": 1}
    assert session.add.call_count == 1
    assert len(captured_events) == 1
    assert captured_events[0][1]["conversation_id"] == str(conv_b)
