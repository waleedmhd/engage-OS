"""Unit tests for `send_outbound_message_task`.

Covers:
- message missing (no-op)
- B-5 regression: non-QUEUED skip log path must not raise AttributeError
  (delivery_status is a String(16) column → plain str, has no `.value`)
- success path → SENT + meta_message_id backfill
- retryable failure schedules retry; non-retryable goes terminal FAILED
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.modules.messaging import tasks as tasks_module
from app.modules.messaging.constants import MessageDeliveryStatus


@pytest.fixture
def patched(monkeypatch):
    session = MagicMock()

    @contextmanager
    def fake_factory():
        yield session

    repo = MagicMock()
    # P1.3: send_outbound_message_task now pauses if Redis is unreachable.
    # These tests exercise the post-gate logic, so treat Redis as healthy.
    monkeypatch.setattr(tasks_module, "redis_healthy", lambda: True)
    monkeypatch.setattr(tasks_module, "sync_session_factory", fake_factory)
    monkeypatch.setattr(tasks_module, "MessageRepository", lambda _s: repo)
    monkeypatch.setattr(
        tasks_module, "_backfill_campaign_recipient_meta_id", lambda *a, **k: None
    )
    return SimpleNamespace(session=session, repo=repo)


def _message(status: str, template_name: str | None = None):
    contact = SimpleNamespace(
        id=uuid.uuid4(),
        phone="+15551234567",
        status="active",
    )
    conversation = SimpleNamespace(contact=contact)
    return SimpleNamespace(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        delivery_status=status,  # plain str (String(16) column)
        content="hello",
        sender_type="agent",
        template_name=template_name,
        template_language=None,
        conversation=conversation,
    )


def test_message_not_found_is_noop(patched):
    patched.repo.get_sync.return_value = None
    tasks_module.send_outbound_message_task.run(str(uuid.uuid4()))
    patched.repo.update_delivery_status_sync.assert_not_called()


def test_b5_non_queued_skip_does_not_raise(patched):
    """B-5: a non-QUEUED message hits the skip-log branch which previously
    did `message.delivery_status.value` — AttributeError on a str.
    Also exercises B-6 (the function-level Meta imports must resolve)."""
    msg = _message("sent")
    patched.repo.get_sync.return_value = msg

    # Must not raise (regression: AttributeError on str.value / ImportError).
    tasks_module.send_outbound_message_task.run(str(msg.id))

    patched.repo.update_delivery_status_sync.assert_not_called()


def test_success_marks_sent_and_backfills(patched, monkeypatch):
    msg = _message(MessageDeliveryStatus.QUEUED.value)
    patched.repo.get_sync.return_value = msg

    fake_client = MagicMock()
    fake_client.send_text.return_value = {"messages": [{"id": "wamid.out.1"}]}
    # M6: the task context-manages the pooled client (`with MetaClient() as
    # client:`), so the mock must return itself from __enter__.
    fake_client.__enter__.return_value = fake_client
    import app.integrations.meta.client as meta_client_mod

    monkeypatch.setattr(
        meta_client_mod, "MetaWhatsAppClient", lambda: fake_client
    )

    tasks_module.send_outbound_message_task.run(str(msg.id))

    kwargs = patched.repo.update_delivery_status_sync.call_args.kwargs
    assert kwargs["new_status"] == MessageDeliveryStatus.SENT
    assert kwargs["meta_message_id"] == "wamid.out.1"


def test_success_bumps_last_message_and_emits_sent(patched, monkeypatch):
    """WhatsApp-style reorder: a successful send must bump the conversation's
    last_message_at and emit a `message.sent` inbox event so live clients
    re-order the conversation to the top."""
    msg = _message(MessageDeliveryStatus.QUEUED.value)
    patched.repo.get_sync.return_value = msg

    fake_client = MagicMock()
    fake_client.send_text.return_value = {"messages": [{"id": "wamid.out.2"}]}
    fake_client.__enter__.return_value = fake_client
    import app.integrations.meta.client as meta_client_mod

    monkeypatch.setattr(
        meta_client_mod, "MetaWhatsAppClient", lambda: fake_client
    )

    # Capture the last_message_at bump and the emitted event.
    conv_repo = MagicMock()
    import app.modules.conversations.repository as conv_repo_mod

    monkeypatch.setattr(
        conv_repo_mod, "ConversationRepository", lambda _s: conv_repo
    )
    import app.core.events as events_mod

    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        events_mod, "emit_event", lambda name, **kw: emitted.append((name, kw))
    )

    tasks_module.send_outbound_message_task.run(str(msg.id))

    conv_repo.touch_last_message_sync.assert_called_once()
    bumped_conv_id = conv_repo.touch_last_message_sync.call_args.args[0]
    assert bumped_conv_id == msg.conversation_id

    assert any(name == "message.sent" for name, _ in emitted)
    sent_kwargs = next(kw for name, kw in emitted if name == "message.sent")
    assert sent_kwargs["conversation_id"] == str(msg.conversation_id)


# ----------------------------------------------------- _handle_send_failure

def test_handle_send_failure_non_retryable_marks_failed():
    from app.core.exceptions import MetaAPIError
    from app.modules.messaging.constants import MessageDeliveryStatus

    repo = MagicMock()
    session = MagicMock()
    task = MagicMock()
    mid = uuid.uuid4()

    tasks_module._handle_send_failure(
        session=session, msg_repo=repo, message_id=mid,
        exc=MetaAPIError("bad"), task=task,
        attempt=0, retryable=False,
    )
    kwargs = repo.update_delivery_status_sync.call_args.kwargs
    assert kwargs["new_status"] == MessageDeliveryStatus.FAILED
    repo.increment_retry_sync.assert_not_called()
    task.retry.assert_not_called()


def test_handle_send_failure_retryable_schedules_retry():
    from app.core.exceptions import MetaAPIError

    repo = MagicMock()
    session = MagicMock()
    task = MagicMock()
    task.retry.side_effect = RuntimeError("retry-raised")
    mid = uuid.uuid4()

    with pytest.raises(RuntimeError):
        tasks_module._handle_send_failure(
            session=session, msg_repo=repo, message_id=mid,
            exc=MetaAPIError("slow"), task=task,
            attempt=0, retryable=True,
        )
    repo.increment_retry_sync.assert_called_once_with(mid)
    task.retry.assert_called_once()


def test_handle_send_failure_retryable_exhausted_marks_failed():
    from app.core.exceptions import MetaAPIError
    from app.modules.messaging.constants import MessageDeliveryStatus

    repo = MagicMock()
    session = MagicMock()
    task = MagicMock()
    mid = uuid.uuid4()

    # attempt past the retry ceiling → terminal FAILED, no retry.
    tasks_module._handle_send_failure(
        session=session, msg_repo=repo, message_id=mid,
        exc=MetaAPIError("slow"), task=task,
        attempt=tasks_module._MAX_RETRIES + 1, retryable=True,
    )
    kwargs = repo.update_delivery_status_sync.call_args.kwargs
    assert kwargs["new_status"] == MessageDeliveryStatus.FAILED
    task.retry.assert_not_called()


def test_system_template_send_uses_send_template_without_components(patched, monkeypatch):
    """SYSTEM sender + template_name → send_template called WITHOUT body components."""
    msg = _message(MessageDeliveryStatus.QUEUED.value, template_name="promo_2024")
    msg.sender_type = "system"
    patched.repo.get_sync.return_value = msg

    fake_client = MagicMock()
    fake_client.send_template.return_value = {"messages": [{"id": "wamid.tpl"}]}
    fake_client.__enter__.return_value = fake_client
    import app.integrations.meta.client as meta_client_mod
    monkeypatch.setattr(meta_client_mod, "MetaWhatsAppClient", lambda: fake_client)

    tasks_module.send_outbound_message_task.run(str(msg.id))

    fake_client.send_template.assert_called_once_with(
        to="+15551234567",
        template_name="promo_2024",
        language="en",
    )
    fake_client.send_text.assert_not_called()


def test_media_file_missing_on_disk_marks_failed(patched, monkeypatch):
    """When _ensure_media_file_on_disk returns False (file missing + no DB blob),
    the task catches the non-retryable MetaAPIError and marks the message FAILED."""
    msg = _message(MessageDeliveryStatus.QUEUED.value)
    media_asset = SimpleNamespace(
        id=uuid.uuid4(),
        file_path="image/missing.jpeg",
        media_type="image",
        mime_type="image/jpeg",
    )
    msg.media = [media_asset]

    patched.repo.get_sync.return_value = msg
    monkeypatch.setattr(tasks_module, "_ensure_media_file_on_disk", lambda _ma: False)

    tasks_module.send_outbound_message_task.run(str(msg.id))

    kwargs = patched.repo.update_delivery_status_sync.call_args.kwargs
    assert kwargs["new_status"] == MessageDeliveryStatus.FAILED
    assert kwargs["last_error"] == "meta_media_file_missing"
