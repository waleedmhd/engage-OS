"""Unit tests for messaging Celery tasks.

Covers:
- Msg-C1: inbound dedup key set ONLY after successful persistence
- Msg-C2: status-update dedup key set ONLY after successful processing
- Msg-I7: ai_enabled checked before NEW→AI_ACTIVE transition (smoke)
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.modules.messaging import tasks as tasks_module
from app.modules.messaging.constants import MessageDeliveryStatus


@pytest.fixture
def mock_redis(monkeypatch):
    """Replace `get_sync_redis` with a MagicMock; return the mock for assertions."""
    redis = MagicMock()
    redis.exists.return_value = False  # default: never deduped
    redis.setex.return_value = True
    monkeypatch.setattr(tasks_module, "get_sync_redis", lambda: redis)
    return redis


@pytest.fixture
def mock_persist(monkeypatch):
    """Replace `_persist_inbound` with a MagicMock so we control its outcome."""
    fn = MagicMock()
    monkeypatch.setattr(tasks_module, "_persist_inbound", fn)
    return fn


@pytest.fixture
def mock_apply_status(monkeypatch):
    fn = MagicMock()
    monkeypatch.setattr(tasks_module, "_apply_status_update", fn)
    return fn


def _inbound_payload(meta_id: str = "wamid.123") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"display_phone_number": "+15551234567"},
                            "messages": [
                                {
                                    "id": meta_id,
                                    "from": "+15551234567",
                                    "type": "text",
                                    "text": {"body": "hello"},
                                    "timestamp": "1700000000",
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def _status_payload(meta_id: str = "wamid.456", status: str = "delivered") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {"id": meta_id, "status": status},
                            ]
                        }
                    }
                ]
            }
        ]
    }


# ----------------------------------------------------------------- Msg-C1

def test_inbound_dedup_key_not_set_on_persist_failure(mock_redis, mock_persist):
    """Msg-C1: if _persist_inbound raises, dedup key MUST NOT be written.

    Regression: previously the key was set BEFORE persistence; a transient
    DB error caused 24h of message loss because Meta retries were silently
    deduplicated.
    """
    mock_persist.side_effect = RuntimeError("simulated DB hiccup")

    # The task uses self.retry which raises — match the bind=True signature.
    fake_self = MagicMock()
    fake_self.retry.side_effect = RuntimeError("retry-raised")

    with pytest.raises(RuntimeError):
        tasks_module.process_inbound_webhook_task.run(_inbound_payload())  # type: ignore[arg-type]
    # NOTE: .run() on a bind=True task expects the task itself as self via
    # decorator magic. If that path doesn't work cleanly we fall back to
    # calling the underlying function directly:
    # tasks_module.process_inbound_webhook_task.__wrapped__(fake_self, _inbound_payload())

    # Critical assertion: dedup key was NOT set despite the iteration entering
    # the try-block.
    mock_redis.setex.assert_not_called()


def test_inbound_dedup_key_set_after_successful_persistence(mock_redis, mock_persist):
    """Sanity: success path sets the key with the 24h TTL."""
    mock_persist.return_value = None  # success

    tasks_module.process_inbound_webhook_task.run(_inbound_payload("wamid.success"))

    mock_persist.assert_called_once()
    mock_redis.setex.assert_called_once()
    args, _ = mock_redis.setex.call_args
    assert args[0] == "dedup:inbound:wamid.success"
    assert args[1] == tasks_module._INBOUND_DEDUP_TTL_SECONDS  # 86400


def test_inbound_dedup_skipped_when_key_exists(mock_redis, mock_persist):
    """If dedup key is already set, persistence MUST NOT be called."""
    mock_redis.exists.return_value = True

    tasks_module.process_inbound_webhook_task.run(_inbound_payload())

    mock_persist.assert_not_called()
    mock_redis.setex.assert_not_called()


# ----------------------------------------------------------------- Msg-C2

def test_status_update_dedup_key_not_set_on_failure(mock_redis, mock_apply_status):
    """Msg-C2: same pattern for status-update dedup."""
    mock_apply_status.side_effect = RuntimeError("simulated DB hiccup")

    with pytest.raises(RuntimeError):
        tasks_module.process_inbound_webhook_task.run(_status_payload())

    mock_redis.setex.assert_not_called()


def test_status_update_dedup_key_set_after_success(mock_redis, mock_apply_status):
    """Sanity: success path writes key with 6h TTL."""
    mock_apply_status.return_value = None

    tasks_module.process_inbound_webhook_task.run(
        _status_payload("wamid.789", "read")
    )

    mock_redis.setex.assert_called_once()
    args, _ = mock_redis.setex.call_args
    assert args[0] == "dedup:status:wamid.789:read"
    assert args[1] == tasks_module._STATUS_DEDUP_TTL_SECONDS  # 21600


# ------------------------------------------------------------- prefetch + _media_local


def _image_payload(meta_id: str = "wamid.img.1") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": meta_id,
                                    "from": "+15551234567",
                                    "type": "image",
                                    "image": {"id": "media-abc", "mime_type": "image/jpeg", "caption": "check this out"},
                                    "timestamp": "1700000000",
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def test_prefetch_inbound_media_stores_file_and_annotates_msg(monkeypatch, tmp_path):
    """prefetch_inbound_media downloads media and writes _media_local on the msg dict."""
    from app.modules.media import service as media_service

    monkeypatch.setattr(media_service, "MEDIA_ROOT", tmp_path)

    fake_binary = b"fake-jpeg-bytes"
    fake_mime = "image/jpeg"

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def download_media(self, *, media_id):
            return fake_binary, fake_mime

    monkeypatch.setattr(
        "app.integrations.meta.client.MetaWhatsAppClient", FakeClient
    )

    payload = _image_payload("wamid.img.1")
    tasks_module.prefetch_inbound_media(payload)

    msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    assert "_media_local" in msg
    local = msg["_media_local"]
    assert local["mime_type"] == "image/jpeg"
    assert local["file_size_bytes"] == len(fake_binary)
    assert local["file_path"].startswith("image/")

    # File was written to disk under tmp_path
    written = tmp_path / local["file_path"]
    assert written.read_bytes() == fake_binary


def test_prefetch_inbound_media_skips_text_messages(monkeypatch):
    """prefetch_inbound_media does nothing for non-media message types."""
    client_calls = []

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def download_media(self, *, media_id):
            client_calls.append(media_id)
            return b"x", "image/png"

    monkeypatch.setattr(
        "app.integrations.meta.client.MetaWhatsAppClient", FakeClient
    )

    payload = _inbound_payload("wamid.text.1")
    tasks_module.prefetch_inbound_media(payload)

    assert client_calls == []  # no media download attempted


def test_prefetch_inbound_media_continues_on_download_failure(monkeypatch, tmp_path):
    """If one media message fails, others still get prefetched."""
    from app.modules.media import service as media_service

    monkeypatch.setattr(media_service, "MEDIA_ROOT", tmp_path)

    class FailingClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def download_media(self, *, media_id):
            raise RuntimeError("simulated download failure")

    monkeypatch.setattr(
        "app.integrations.meta.client.MetaWhatsAppClient", FailingClient
    )

    payload = _image_payload("wamid.img.fail")
    tasks_module.prefetch_inbound_media(payload)

    msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    assert "_media_local" not in msg  # download failed, so no annotation


def test_download_and_store_media_uses_prefetched_local():
    """_download_and_store_media uses _media_local when present, skipping download."""
    from app.modules.media.models import MediaAsset

    msg = {
        "type": "image",
        "image": {"id": "media-xyz"},
        "_media_local": {
            "asset_id": "00000000-0000-0000-0000-000000000001",
            "file_path": "image/f0000001.jpg",
            "mime_type": "image/jpeg",
            "file_size_bytes": 42,
        },
    }

    session = MagicMock()
    message_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    tasks_module._download_and_store_media(
        session,
        media_id="media-xyz",
        msg_type="image",
        message_id=message_id,
        msg=msg,
    )

    # _media_local should be consumed (popped off)
    assert "_media_local" not in msg

    # A MediaAsset was added to the session with the prefetched values
    session.add.assert_called_once()
    asset = session.add.call_args[0][0]
    assert isinstance(asset, MediaAsset)
    assert str(asset.id) == "00000000-0000-0000-0000-000000000001"
    assert asset.file_path == "image/f0000001.jpg"
    assert asset.mime_type == "image/jpeg"
    assert asset.file_size_bytes == 42


# --------------------------------------------------- delivery-failure retry


def _failed_message():
    """Return a SimpleNamespace matching what reset_and_retry_message_task
    reads from the DB after a delivery failure."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        delivery_status=MessageDeliveryStatus.FAILED.value,
        delivery_retry_count=1,
    )


class TestResetAndRetryMessageTask:
    def test_resets_to_queued_and_dispatches_send(self, monkeypatch):
        """Happy path: FAILED -> QUEUED + send_outbound_message_task.delay."""
        import app.modules.messaging.tasks as tasks_module

        msg = _failed_message()

        session = MagicMock()
        repo = MagicMock()
        repo.get_sync.return_value = msg

        @contextmanager
        def fake_factory():
            yield session

        monkeypatch.setattr(tasks_module, "sync_session_factory", fake_factory)
        monkeypatch.setattr(tasks_module, "MessageRepository", lambda _s: repo)
        monkeypatch.setattr(
            "app.modules.settings.repository.get_bool_setting_sync",
            lambda s, k, default: True,
        )
        mock_send = MagicMock()
        monkeypatch.setattr(tasks_module, "send_outbound_message_task", mock_send)

        tasks_module.reset_and_retry_message_task.run(str(msg.id), 0)

        # Verify status reset.
        kwargs = repo.update_delivery_status_sync.call_args.kwargs
        assert kwargs["new_status"] == MessageDeliveryStatus.QUEUED
        assert kwargs["last_error"] is None
        assert kwargs["error_code"] is None
        assert kwargs["meta_message_id"] is None

        # Verify atomic increment.
        repo.increment_delivery_retry_sync.assert_called_once_with(msg.id)

        # Verify dispatch.
        mock_send.delay.assert_called_once_with(str(msg.id))

    def test_skips_when_setting_disabled(self, monkeypatch):
        """If setting was toggled off between scheduling and execution, noop."""
        import app.modules.messaging.tasks as tasks_module

        msg = _failed_message()
        session = MagicMock()
        repo = MagicMock()
        repo.get_sync.return_value = msg

        @contextmanager
        def fake_factory():
            yield session

        monkeypatch.setattr(tasks_module, "sync_session_factory", fake_factory)
        monkeypatch.setattr(tasks_module, "MessageRepository", lambda _s: repo)
        monkeypatch.setattr(
            "app.modules.settings.repository.get_bool_setting_sync",
            lambda s, k, default: False,
        )
        mock_send = MagicMock()
        monkeypatch.setattr(tasks_module, "send_outbound_message_task", mock_send)

        tasks_module.reset_and_retry_message_task.run(str(msg.id), 0)

        repo.update_delivery_status_sync.assert_not_called()
        mock_send.delay.assert_not_called()

    def test_skips_when_not_failed(self, monkeypatch):
        """If message was re-delivered by a late webhook since scheduling, noop."""
        import app.modules.messaging.tasks as tasks_module

        msg = _failed_message()
        msg.delivery_status = MessageDeliveryStatus.DELIVERED.value

        session = MagicMock()
        repo = MagicMock()
        repo.get_sync.return_value = msg

        @contextmanager
        def fake_factory():
            yield session

        monkeypatch.setattr(tasks_module, "sync_session_factory", fake_factory)
        monkeypatch.setattr(tasks_module, "MessageRepository", lambda _s: repo)
        monkeypatch.setattr(
            "app.modules.settings.repository.get_bool_setting_sync",
            lambda s, k, default: True,
        )
        mock_send = MagicMock()
        monkeypatch.setattr(tasks_module, "send_outbound_message_task", mock_send)

        tasks_module.reset_and_retry_message_task.run(str(msg.id), 0)

        repo.update_delivery_status_sync.assert_not_called()
        mock_send.delay.assert_not_called()

    def test_skips_when_message_not_found(self, monkeypatch):
        """Message may have been deleted between scheduling and execution."""
        import app.modules.messaging.tasks as tasks_module

        session = MagicMock()
        repo = MagicMock()
        repo.get_sync.return_value = None

        @contextmanager
        def fake_factory():
            yield session

        monkeypatch.setattr(tasks_module, "sync_session_factory", fake_factory)
        monkeypatch.setattr(tasks_module, "MessageRepository", lambda _s: repo)
        monkeypatch.setattr(
            "app.modules.settings.repository.get_bool_setting_sync",
            lambda s, k, default: True,
        )
        mock_send = MagicMock()
        monkeypatch.setattr(tasks_module, "send_outbound_message_task", mock_send)

        tasks_module.reset_and_retry_message_task.run(str(uuid.uuid4()), 0)

        repo.update_delivery_status_sync.assert_not_called()
        mock_send.delay.assert_not_called()

    def test_setting_read_error_is_noop(self, monkeypatch):
        """If the setting read raises, fail safe -- do not reset or dispatch."""
        import app.modules.messaging.tasks as tasks_module

        session = MagicMock()
        repo = MagicMock()

        @contextmanager
        def fake_factory():
            yield session

        monkeypatch.setattr(tasks_module, "sync_session_factory", fake_factory)
        monkeypatch.setattr(tasks_module, "MessageRepository", lambda _s: repo)
        monkeypatch.setattr(
            "app.modules.settings.repository.get_bool_setting_sync",
            lambda s, k, default: (_ for _ in ()).throw(RuntimeError("db down")),
        )
        mock_send = MagicMock()
        monkeypatch.setattr(tasks_module, "send_outbound_message_task", mock_send)

        # Must not raise.
        tasks_module.reset_and_retry_message_task.run(str(uuid.uuid4()), 0)

        repo.update_delivery_status_sync.assert_not_called()
        mock_send.delay.assert_not_called()

    def test_increments_delivery_retry_count(self, monkeypatch):
        """delivery_retry_count is incremented atomically before reset."""
        import app.modules.messaging.tasks as tasks_module

        msg = _failed_message()
        session = MagicMock()
        repo = MagicMock()
        repo.get_sync.return_value = msg

        @contextmanager
        def fake_factory():
            yield session

        monkeypatch.setattr(tasks_module, "sync_session_factory", fake_factory)
        monkeypatch.setattr(tasks_module, "MessageRepository", lambda _s: repo)
        monkeypatch.setattr(
            "app.modules.settings.repository.get_bool_setting_sync",
            lambda s, k, default: True,
        )
        mock_send = MagicMock()
        monkeypatch.setattr(tasks_module, "send_outbound_message_task", mock_send)

        tasks_module.reset_and_retry_message_task.run(str(msg.id), 1)

        repo.increment_delivery_retry_sync.assert_called_once_with(msg.id)
