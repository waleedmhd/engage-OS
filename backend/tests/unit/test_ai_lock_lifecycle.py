"""AI Redis lock lifecycle (architectural invariant #11).

Asserts:
  * First worker acquires the lock and runs the orchestrator.
  * Second worker (lock already held) short-circuits with ai_lock_held noop.
  * Lock is released in `finally` even when the orchestrator raises.
  * Lock TTL is set (key would expire if release never runs).

All exercised against a fakeredis instance; no real Redis required.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _patched_redis(fake_redis):
    """Patch app.core.redis.get_sync_redis to return fakeredis for the duration
    of the test, so the AI task's lock helpers operate against fakeredis."""
    with patch("app.modules.ai.tasks.get_sync_redis", return_value=fake_redis):
        yield fake_redis


def _patch_session_and_orchestrator(orch_mock):
    """Replace sync_session_factory with a context-manager-friendly stub
    and AIOrchestrator with a MagicMock whose process_inbound returns ``orch_mock``."""
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    conv = MagicMock(ai_enabled=True, state="ai_thinking")
    session.get = MagicMock(return_value=conv)

    sf = MagicMock()
    sf.return_value = session

    orch = MagicMock()
    orch.process_inbound = MagicMock(return_value=orch_mock)
    return sf, orch, session


def test_first_call_acquires_lock_and_runs(_patched_redis):
    from app.modules.ai import tasks as ai_tasks

    decision = MagicMock(action="approval", delay_seconds=None, draft_message_id=None,
                         tag_suggestion_ids=[], reason="needs_human")
    sf, orch, _session = _patch_session_and_orchestrator(decision)

    conv_id = str(uuid.uuid4())
    with patch.object(ai_tasks, "sync_session_factory", sf), \
         patch.object(ai_tasks, "AIOrchestrator", return_value=orch):
        result = ai_tasks.request_ai_reply_task.run(conv_id, "hello")

    assert result["action"] == "approval"
    # Lock must be released after the task returns.
    assert _patched_redis.get(f"ai:lock:conv:{conv_id}") is None


def test_second_call_while_locked_returns_noop(_patched_redis):
    from app.modules.ai import tasks as ai_tasks

    conv_id = str(uuid.uuid4())
    # Pre-populate the lock — simulates worker A still running.
    _patched_redis.set(f"ai:lock:conv:{conv_id}", "1", nx=True, ex=180)

    # Worker B's call should short-circuit without touching the orchestrator.
    sentinel = MagicMock(side_effect=AssertionError("orchestrator must not run"))
    with patch.object(ai_tasks, "AIOrchestrator", sentinel):
        result = ai_tasks.request_ai_reply_task.run(conv_id, "hello")

    assert result == {"action": "noop", "reason": "ai_lock_held"}
    sentinel.assert_not_called()


def test_lock_released_when_orchestrator_raises(_patched_redis):
    from app.core.exceptions import AIProviderError
    from app.modules.ai import tasks as ai_tasks

    sf, _orch, _session = _patch_session_and_orchestrator(MagicMock())
    # Replace orchestrator with one that raises a non-retryable AIProviderError.
    raising_orch = MagicMock()
    raising_orch.process_inbound = MagicMock(side_effect=AIProviderError("boom", retryable=False))
    fallback_orch = MagicMock()
    fallback_orch.assign_human = MagicMock(return_value=None)

    conv_id = str(uuid.uuid4())

    def orch_factory(session=None):
        # First call returns the raising orchestrator; second (fallback) returns the assign-human stub.
        if not hasattr(orch_factory, "_called"):
            orch_factory._called = True
            return raising_orch
        return fallback_orch

    with patch.object(ai_tasks, "sync_session_factory", sf), \
         patch.object(ai_tasks, "AIOrchestrator", side_effect=orch_factory):
        result = ai_tasks.request_ai_reply_task.run(conv_id, "hello")

    # Outcome: escalated path, fallback orchestrator was used.
    assert result["action"] == "escalate"
    # Lock released even though the inner orchestrator raised.
    assert _patched_redis.get(f"ai:lock:conv:{conv_id}") is None


def test_lock_key_has_ttl(_patched_redis):
    """Lock must be set with a TTL — a leaked lock without TTL would block
    the conversation forever if the worker died mid-task."""
    from app.modules.ai import tasks as ai_tasks

    sf, orch, _session = _patch_session_and_orchestrator(
        MagicMock(action="approval", delay_seconds=None, draft_message_id=None,
                  tag_suggestion_ids=[], reason="r")
    )
    conv_id = str(uuid.uuid4())

    captured_ttl = {}
    real_set = _patched_redis.set

    def capturing_set(name, value, nx=False, ex=None, **kw):
        if name.startswith("ai:lock:conv:"):
            captured_ttl["ex"] = ex
            captured_ttl["nx"] = nx
        return real_set(name, value, nx=nx, ex=ex, **kw)

    _patched_redis.set = capturing_set
    try:
        with patch.object(ai_tasks, "sync_session_factory", sf), \
             patch.object(ai_tasks, "AIOrchestrator", return_value=orch):
            ai_tasks.request_ai_reply_task.run(conv_id, "hello")
    finally:
        _patched_redis.set = real_set

    assert captured_ttl["nx"] is True
    assert captured_ttl["ex"] is not None
    assert captured_ttl["ex"] >= 60, "TTL must be long enough to cover the retry window"
