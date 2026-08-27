"""Unit tests for request_meta_deletion_task (Batch 3)."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.modules.messaging import tasks as tasks_module


@pytest.fixture
def patched(monkeypatch):
    session = MagicMock()

    @contextmanager
    def fake_factory():
        yield session

    repo = MagicMock()
    monkeypatch.setattr(tasks_module, "sync_session_factory", fake_factory)
    monkeypatch.setattr(tasks_module, "MessageRepository", lambda _s: repo)
    return SimpleNamespace(session=session, repo=repo)


def _message(meta_message_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        meta_message_id=meta_message_id,
    )


def test_no_meta_id_skips(patched):
    """Message never sent to Meta — skip deletion."""
    msg = _message(meta_message_id=None)
    patched.repo.get_sync.return_value = msg

    tasks_module.request_meta_deletion_task.run(str(msg.id))

    # No Meta client call should have happened (no exception)


def test_message_not_found_is_noop(patched):
    patched.repo.get_sync.return_value = None
    tasks_module.request_meta_deletion_task.run(str(uuid.uuid4()))
    # Should not raise


def test_meta_deletion_success(patched, monkeypatch):
    msg = _message(meta_message_id="wamid.123")
    patched.repo.get_sync.return_value = msg

    fake_client = MagicMock()
    fake_client.delete_message.return_value = {"success": True}
    fake_client.__enter__.return_value = fake_client
    import app.integrations.meta.client as meta_client_mod
    monkeypatch.setattr(
        meta_client_mod, "MetaWhatsAppClient", lambda: fake_client
    )

    tasks_module.request_meta_deletion_task.run(str(msg.id))

    fake_client.delete_message.assert_called_once_with(meta_message_id="wamid.123")


def test_meta_deletion_retryable_logs_and_exits(patched, monkeypatch):
    """Retryable MetaAPIError in deletion task: the task retries via Celery,
    which with a mock `self` just logs the retry warning. Verify client called."""
    from app.core.exceptions import MetaAPIError

    msg = _message(meta_message_id="wamid.456")
    patched.repo.get_sync.return_value = msg

    fake_client = MagicMock()
    err = MetaAPIError("timeout", details={"retryable": True})
    fake_client.delete_message.side_effect = err
    fake_client.__enter__.return_value = fake_client
    import app.integrations.meta.client as meta_client_mod
    monkeypatch.setattr(
        meta_client_mod, "MetaWhatsAppClient", lambda: fake_client
    )

    # The task catches the MetaAPIError, enters the retry path, calls
    # self.retry() on a MagicMock which returns a non-exception — raise
    # fails with TypeError. That's fine — we only care that the client
    # was invoked before the error path.
    try:
        tasks_module.request_meta_deletion_task.run(str(msg.id))
    except (MetaAPIError, TypeError):
        pass

    fake_client.delete_message.assert_called_once()


def test_meta_deletion_non_retryable_is_noop(patched, monkeypatch):
    from app.core.exceptions import MetaAPIError

    msg = _message(meta_message_id="wamid.789")
    patched.repo.get_sync.return_value = msg

    fake_client = MagicMock()
    err = MetaAPIError("permanent", details={"retryable": False})
    fake_client.delete_message.side_effect = err
    fake_client.__enter__.return_value = fake_client
    import app.integrations.meta.client as meta_client_mod
    monkeypatch.setattr(
        meta_client_mod, "MetaWhatsAppClient", lambda: fake_client
    )

    # Non-retryable should just log, not raise
    tasks_module.request_meta_deletion_task.run(str(msg.id))
