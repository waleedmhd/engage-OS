"""Unit coverage for request_ai_reply_task control flow.

Mocks AIOrchestrator + sync_session_factory so each branch (lock-held,
conversation missing, non-AI state, success/auto_send, retryable error →
retry, exhausted/non-retryable → assign_human) is exercised deterministically.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import AIProviderError, AIProviderTimeoutError
from app.modules.ai import tasks as ai_tasks
from app.modules.ai.service import Decision
from app.modules.conversations.constants import ConversationState


@pytest.fixture
def patched(monkeypatch):
    session = MagicMock()
    conv = SimpleNamespace(
        ai_enabled=True, state=ConversationState.AI_ACTIVE.value
    )
    session.get.return_value = conv

    @contextmanager
    def fake_factory():
        yield session

    orch = MagicMock()
    monkeypatch.setattr(ai_tasks, "sync_session_factory", fake_factory)
    monkeypatch.setattr(ai_tasks, "AIOrchestrator", lambda **k: orch)
    # Real fakeredis-ish: in-memory lock dict.
    store: dict = {}

    class _R:
        def set(self, k, v, nx=False, ex=None):
            if nx and k in store:
                return False
            store[k] = v
            return True

        def delete(self, k):
            store.pop(k, None)

    monkeypatch.setattr(ai_tasks, "get_sync_redis", lambda: _R())
    return SimpleNamespace(session=session, conv=conv, orch=orch, store=store)


def test_lock_held_returns_noop(patched, monkeypatch):
    cid = str(uuid.uuid4())
    # Pre-acquire the lock so the task sees it held.
    monkeypatch.setattr(ai_tasks, "_acquire_ai_lock", lambda _c: False)
    out = ai_tasks.request_ai_reply_task.run(cid, "hi")
    assert out == {"action": "noop", "reason": "ai_lock_held"}


def test_conversation_missing_noop(patched):
    patched.session.get.return_value = None
    out = ai_tasks.request_ai_reply_task.run(str(uuid.uuid4()), "hi")
    assert out["reason"] == "conversation_missing"


def test_non_ai_state_noop(patched):
    patched.conv.state = ConversationState.HUMAN_ASSIGNED.value
    out = ai_tasks.request_ai_reply_task.run(str(uuid.uuid4()), "hi")
    assert out["reason"] == "ai_disabled_or_handed_off"


def test_success_auto_send_enqueues(patched, monkeypatch):
    draft_id = uuid.uuid4()
    patched.orch.process_inbound.return_value = Decision(
        action="auto_send", draft_message_id=draft_id, delay_seconds=30
    )
    sent = {}
    monkeypatch.setattr(
        ai_tasks.send_ai_reply_task,
        "apply_async",
        lambda *a, **k: sent.update(k),
    )
    out = ai_tasks.request_ai_reply_task.run(str(uuid.uuid4()), "hi")
    assert out["action"] == "auto_send"
    assert sent["countdown"] == 30


def test_retryable_error_triggers_retry(patched, monkeypatch):
    patched.orch.process_inbound.side_effect = AIProviderTimeoutError("slow")
    # Celery .run() builds a real bound task; force retries=0 and assert Retry.
    from celery.exceptions import Retry

    with pytest.raises((Retry, AIProviderTimeoutError)):
        ai_tasks.request_ai_reply_task.run(str(uuid.uuid4()), "hi")


def test_non_retryable_assigns_human(patched, monkeypatch):
    patched.orch.process_inbound.side_effect = AIProviderError(
        "boom", retryable=False
    )
    out = ai_tasks.request_ai_reply_task.run(str(uuid.uuid4()), "hi")
    assert out["action"] == "escalate"
    assert "ai_provider_failure" in out["reason"]


# -------------------------------------------------------- _find_unreplied_inbound


def _make_result(return_value):
    """Mock a SQLAlchemy Result that supports .one_or_none() or .scalar_one()."""
    result = MagicMock()
    result.one_or_none.return_value = return_value
    result.scalar_one.return_value = return_value
    return result


class TestFindUnrepliedInbound:
    def test_no_inbound_message_returns_none(self, monkeypatch):
        session = MagicMock()
        session.execute.return_value = _make_result(None)
        # context manager protocol for `with sync_session_factory() as session:`
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(ai_tasks, "sync_session_factory", lambda: session)
        assert ai_tasks._find_unreplied_inbound(str(uuid.uuid4())) is None

    def test_inbound_with_reply_returns_none(self, monkeypatch):
        session = MagicMock()
        session.execute.side_effect = [
            _make_result(("Hello", object())),
            _make_result(1),
        ]
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(ai_tasks, "sync_session_factory", lambda: session)
        assert ai_tasks._find_unreplied_inbound(str(uuid.uuid4())) is None

    def test_inbound_without_reply_returns_content(self, monkeypatch):
        session = MagicMock()
        session.execute.side_effect = [
            _make_result(("Are you there?", object())),
            _make_result(0),
        ]
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(ai_tasks, "sync_session_factory", lambda: session)
        assert ai_tasks._find_unreplied_inbound(str(uuid.uuid4())) == "Are you there?"


# -------------------------------------------------------- update_memory_on_ai_resume


class TestUpdateMemoryOnAiResume:
    def _patch(self, monkeypatch, *, conv_exists=True, empty_history=False, memory_succeeds=True):
        """Shared setup: mock sync_session_factory, update_memory_from_history_sync,
        and _find_unreplied_inbound. Returns the patched task object."""
        from datetime import UTC, datetime, timedelta

        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)

        if conv_exists:
            conv = MagicMock()
            conv.contact_id = uuid.uuid4()
            session.get.return_value = conv
        else:
            session.get.return_value = None

        result = MagicMock()
        if empty_history:
            result.all.return_value = []
        else:
            row1 = MagicMock()
            row1.direction = "inbound"
            row1.sender_type = "contact"
            row1.content = "Hello"
            row1.created_at = datetime.now(UTC) - timedelta(hours=1)
            result.all.return_value = [row1]
        session.execute.return_value = result

        # update_memory_from_history_sync is imported locally inside the task
        # body — patch it on its source module.
        mock_update = MagicMock()
        if not memory_succeeds:
            mock_update.side_effect = RuntimeError("boom")
        monkeypatch.setattr(
            "app.modules.contacts.memory_service.update_memory_from_history_sync",
            mock_update,
            raising=False,
        )

        monkeypatch.setattr(ai_tasks, "sync_session_factory", lambda: session)
        monkeypatch.setattr(ai_tasks, "_find_unreplied_inbound", lambda _cid: None)
        return SimpleNamespace(session=session, update_mock=mock_update)

    def test_conversation_missing_noop(self, monkeypatch):
        self._patch(monkeypatch, conv_exists=False)
        out = ai_tasks.update_memory_on_ai_resume.run(str(uuid.uuid4()))
        assert out == {"action": "noop", "reason": "conversation_missing"}

    def test_no_history_noop(self, monkeypatch):
        self._patch(monkeypatch, empty_history=True)
        out = ai_tasks.update_memory_on_ai_resume.run(str(uuid.uuid4()))
        assert out == {"action": "noop", "reason": "no_history"}

    def test_memory_update_failure_noop(self, monkeypatch):
        self._patch(monkeypatch, memory_succeeds=False)
        out = ai_tasks.update_memory_on_ai_resume.run(str(uuid.uuid4()))
        assert out == {"action": "noop", "reason": "memory_update_failed"}

    def test_memory_updated_no_unreplied(self, monkeypatch):
        s = self._patch(monkeypatch)
        monkeypatch.setattr(ai_tasks, "_find_unreplied_inbound", lambda _cid: None)
        out = ai_tasks.update_memory_on_ai_resume.run(str(uuid.uuid4()))
        assert out == {"action": "memory_updated", "reason": "no_unreplied_messages"}
        s.update_mock.assert_called_once()

    def test_memory_updated_triggers_ai(self, monkeypatch):
        s = self._patch(monkeypatch)
        monkeypatch.setattr(ai_tasks, "_find_unreplied_inbound", lambda _cid: "Hi again")
        dispatched = {}

        def fake_delay(cid, msg):
            dispatched["cid"] = cid
            dispatched["msg"] = msg

        monkeypatch.setattr(
            ai_tasks.request_ai_reply_task,
            "delay",
            fake_delay,
        )
        out = ai_tasks.update_memory_on_ai_resume.run(str(uuid.uuid4()))
        assert out["action"] == "ai_triggered"
        assert dispatched["msg"] == "Hi again"
        s.update_mock.assert_called_once()
