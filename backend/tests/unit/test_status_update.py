"""Unit tests for messaging `_apply_status_update`.

Covers the delivery-status callback path, including:
- unknown status string (no-op)
- message not found (no-op)
- READ downgrade guard
- B-4 regression: delivery status must be monotonic — an out-of-order
  `sent`/`delivered` callback must NOT overwrite a better state.
- FAILED carries the errors JSON
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.modules.messaging.constants import (
    DELIVERY_FAILURE_RETRY_DELAYS,
    MAX_DELIVERY_RETRIES,
)

import pytest

from app.modules.messaging import tasks as tasks_module
from app.modules.messaging.constants import MessageDeliveryStatus


@pytest.fixture
def patched(monkeypatch):
    """Patch sync_session_factory + MessageRepository + campaign propagate.

    Returns the fake MessageRepository instance so tests can assert on
    update_delivery_status_sync calls.
    """
    session = MagicMock()

    @contextmanager
    def fake_factory():
        yield session

    repo = MagicMock()
    monkeypatch.setattr(tasks_module, "sync_session_factory", fake_factory)
    monkeypatch.setattr(tasks_module, "MessageRepository", lambda _s: repo)
    monkeypatch.setattr(tasks_module, "_propagate_to_campaign_recipient", lambda *a, **k: None)
    return repo


def _existing(status: str):
    # delivery_status is a String(16) column → loaded as a plain str.
    return SimpleNamespace(
        id=uuid.uuid4(),
        delivery_status=status,
        delivery_retry_count=0,
    )


def _existing_with_drc(status: str, delivery_retry_count: int = 0):
    return SimpleNamespace(
        id=uuid.uuid4(),
        delivery_status=status,
        delivery_retry_count=delivery_retry_count,
    )


def test_unknown_status_is_noop(patched):
    tasks_module._apply_status_update("wamid.x", "bogus", {})
    patched.update_delivery_status_sync.assert_not_called()


def test_message_not_found_is_noop(patched):
    patched.get_by_meta_id_sync.return_value = None
    tasks_module._apply_status_update("wamid.x", "delivered", {})
    patched.update_delivery_status_sync.assert_not_called()


def test_read_is_not_downgraded(patched):
    patched.get_by_meta_id_sync.return_value = _existing("read")
    tasks_module._apply_status_update("wamid.x", "delivered", {})
    patched.update_delivery_status_sync.assert_not_called()


def test_valid_advance_delivered_to_read(patched):
    patched.get_by_meta_id_sync.return_value = _existing("delivered")
    tasks_module._apply_status_update("wamid.x", "read", {})
    patched.update_delivery_status_sync.assert_called_once()
    assert (
        patched.update_delivery_status_sync.call_args.kwargs["new_status"]
        == MessageDeliveryStatus.READ
    )


def test_failed_carries_error_json(patched, monkeypatch):
    patched.get_by_meta_id_sync.return_value = _existing("sent")
    # Stub the delivery-retry path so it doesn't try to contact Celery/Redis.
    monkeypatch.setattr(tasks_module, "reset_and_retry_message_task", MagicMock())
    import app.modules.settings.repository as settings_repo

    monkeypatch.setattr(settings_repo, "get_bool_setting_sync", lambda s, k, default: True)
    tasks_module._apply_status_update(
        "wamid.x", "failed", {"errors": [{"code": 131, "title": "boom"}]}
    )
    kwargs = patched.update_delivery_status_sync.call_args.kwargs
    assert kwargs["new_status"] == MessageDeliveryStatus.FAILED
    assert json.loads(kwargs["last_error"]) == {"code": 131, "title": "boom"}


# ----------------------------------------------------------------- B-4

@pytest.mark.parametrize(
    "current,incoming",
    [
        ("delivered", "sent"),       # late SENT after DELIVERED
        ("read", "sent"),            # late SENT after READ
        ("delivered", "delivered"),  # duplicate, no advance
    ],
)
def test_b4_out_of_order_does_not_downgrade(patched, current, incoming):
    """B-4: delivery status is monotonic; a stale/duplicate callback that
    does not strictly advance the status must NOT issue an UPDATE."""
    patched.get_by_meta_id_sync.return_value = _existing(current)
    tasks_module._apply_status_update("wamid.x", incoming, {})
    patched.update_delivery_status_sync.assert_not_called()


def test_b4_failed_after_delivered_does_not_regress(patched):
    """A `failed` callback arriving after `delivered` must not regress the
    row — DELIVERED is a stronger signal than FAILED for an already
    delivered message."""
    patched.get_by_meta_id_sync.return_value = _existing("delivered")
    tasks_module._apply_status_update("wamid.x", "failed", {})
    patched.update_delivery_status_sync.assert_not_called()


# --------------------------------------------------- delivery-failure retry


def test_failed_schedules_delivery_retry_when_enabled(patched, monkeypatch):
    """When setting is enabled and retries remain, a FAILED status schedules
    reset_and_retry_message_task with the correct countdown."""
    msg = _existing_with_drc("sent", delivery_retry_count=0)
    patched.get_by_meta_id_sync.return_value = msg

    mock_task = MagicMock()
    monkeypatch.setattr(tasks_module, "reset_and_retry_message_task", mock_task)
    import app.modules.settings.repository as settings_repo

    monkeypatch.setattr(settings_repo, "get_bool_setting_sync", lambda s, k, default: True)

    tasks_module._apply_status_update("wamid.x", "failed", {})

    mock_task.apply_async.assert_called_once()
    _, kwargs = mock_task.apply_async.call_args
    assert kwargs["countdown"] == DELIVERY_FAILURE_RETRY_DELAYS[0]
    assert kwargs["args"] == (str(msg.id), 0)


def test_failed_no_retry_when_setting_disabled(patched, monkeypatch):
    """When the operational setting is disabled, no retry is scheduled."""
    msg = _existing_with_drc("sent", delivery_retry_count=0)
    patched.get_by_meta_id_sync.return_value = msg

    mock_task = MagicMock()
    monkeypatch.setattr(tasks_module, "reset_and_retry_message_task", mock_task)
    import app.modules.settings.repository as settings_repo

    monkeypatch.setattr(settings_repo, "get_bool_setting_sync", lambda s, k, default: False)

    tasks_module._apply_status_update("wamid.x", "failed", {})

    mock_task.apply_async.assert_not_called()


def test_failed_no_retry_when_retries_exhausted(patched, monkeypatch):
    """When delivery_retry_count >= MAX_DELIVERY_RETRIES, no retry is scheduled."""
    msg = _existing_with_drc("sent", delivery_retry_count=MAX_DELIVERY_RETRIES)
    patched.get_by_meta_id_sync.return_value = msg

    mock_task = MagicMock()
    monkeypatch.setattr(tasks_module, "reset_and_retry_message_task", mock_task)
    import app.modules.settings.repository as settings_repo

    # Setting is enabled — but retries are exhausted, so it should still noop.
    monkeypatch.setattr(settings_repo, "get_bool_setting_sync", lambda s, k, default: True)

    tasks_module._apply_status_update("wamid.x", "failed", {})

    mock_task.apply_async.assert_not_called()


def test_failed_second_attempt_uses_3h_countdown(patched, monkeypatch):
    """delivery_retry_count=1 → second attempt → 10800s (3h) countdown."""
    msg = _existing_with_drc("sent", delivery_retry_count=1)
    patched.get_by_meta_id_sync.return_value = msg

    mock_task = MagicMock()
    monkeypatch.setattr(tasks_module, "reset_and_retry_message_task", mock_task)
    import app.modules.settings.repository as settings_repo

    monkeypatch.setattr(settings_repo, "get_bool_setting_sync", lambda s, k, default: True)

    tasks_module._apply_status_update("wamid.x", "failed", {})

    _, kwargs = mock_task.apply_async.call_args
    assert kwargs["countdown"] == DELIVERY_FAILURE_RETRY_DELAYS[1]  # 10800
    assert kwargs["args"] == (str(msg.id), 1)


def test_failed_third_attempt_uses_12h_countdown(patched, monkeypatch):
    """delivery_retry_count=2 → third attempt → 43200s (12h) countdown."""
    msg = _existing_with_drc("sent", delivery_retry_count=2)
    patched.get_by_meta_id_sync.return_value = msg

    mock_task = MagicMock()
    monkeypatch.setattr(tasks_module, "reset_and_retry_message_task", mock_task)
    import app.modules.settings.repository as settings_repo

    monkeypatch.setattr(settings_repo, "get_bool_setting_sync", lambda s, k, default: True)

    tasks_module._apply_status_update("wamid.x", "failed", {})

    _, kwargs = mock_task.apply_async.call_args
    assert kwargs["countdown"] == DELIVERY_FAILURE_RETRY_DELAYS[2]  # 43200
    assert kwargs["args"] == (str(msg.id), 2)


def test_failed_no_retry_on_non_failed_status(patched, monkeypatch):
    """Only FAILED status triggers retry scheduling — DELIVERED, READ, SENT do not."""
    msg = _existing_with_drc("sent", delivery_retry_count=0)
    patched.get_by_meta_id_sync.return_value = msg

    mock_task = MagicMock()
    monkeypatch.setattr(tasks_module, "reset_and_retry_message_task", mock_task)
    import app.modules.settings.repository as settings_repo

    monkeypatch.setattr(settings_repo, "get_bool_setting_sync", lambda s, k, default: True)

    tasks_module._apply_status_update("wamid.x", "delivered", {})
    mock_task.apply_async.assert_not_called()


def test_failed_setting_read_error_is_noop(patched, monkeypatch):
    """If the setting read raises (e.g. DB hiccup), fail safe — no retry scheduled."""
    msg = _existing_with_drc("sent", delivery_retry_count=0)
    patched.get_by_meta_id_sync.return_value = msg

    mock_task = MagicMock()
    monkeypatch.setattr(tasks_module, "reset_and_retry_message_task", mock_task)
    import app.modules.settings.repository as settings_repo

    monkeypatch.setattr(
        settings_repo,
        "get_bool_setting_sync",
        lambda s, k, default: (_ for _ in ()).throw(RuntimeError("db down")),
    )

    # Must not raise — setting read failures are swallowed.
    tasks_module._apply_status_update("wamid.x", "failed", {})

    mock_task.apply_async.assert_not_called()
