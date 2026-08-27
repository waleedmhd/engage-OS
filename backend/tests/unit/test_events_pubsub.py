"""P2.1 — cross-process inbox event fan-out (app.core.events).

Covers the Redis pub/sub publish hook added to `emit_event`:
  * inbox-relevant events (message.* / conversation.*) are published to
    INBOX_PUBSUB_CHANNEL as JSON,
  * other domains are NOT relayed,
  * a Redis failure is swallowed (best-effort — must not break the domain
    write path, DSD §11).
"""

from __future__ import annotations

import json

import pytest

from app.core.events import INBOX_PUBSUB_CHANNEL, emit_event


class _RecordingRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, message))


@pytest.fixture
def recording_redis(monkeypatch) -> _RecordingRedis:
    rec = _RecordingRedis()
    monkeypatch.setattr("app.core.redis.get_sync_redis", lambda: rec)
    return rec


def test_message_event_is_relayed(recording_redis) -> None:
    emit_event("message.received", conversation_id="c1", meta_message_id="wamid.X")

    assert len(recording_redis.published) == 1
    channel, payload = recording_redis.published[0]
    assert channel == INBOX_PUBSUB_CHANNEL
    decoded = json.loads(payload)
    assert decoded["event"] == "message.received"
    assert decoded["conversation_id"] == "c1"


def test_conversation_event_is_relayed(recording_redis) -> None:
    emit_event("conversation.first_activated", conversation_id="c2")

    assert len(recording_redis.published) == 1
    assert json.loads(recording_redis.published[0][1])["event"] == (
        "conversation.first_activated"
    )


def test_unrelated_event_not_relayed(recording_redis) -> None:
    emit_event("tag.suggested", contact_id="x")
    emit_event("campaign.launched", campaign_id="y")

    assert recording_redis.published == []


def test_publish_failure_is_swallowed(monkeypatch) -> None:
    class _BoomRedis:
        def publish(self, *a, **k):
            raise RuntimeError("redis down")

    monkeypatch.setattr("app.core.redis.get_sync_redis", lambda: _BoomRedis())

    # Must not raise — the domain event has already been committed upstream.
    emit_event("message.received", conversation_id="c3")


def test_non_json_payload_is_serialized_via_default_str(recording_redis) -> None:
    import uuid

    cid = uuid.uuid4()
    emit_event("conversation.assigned", conversation_id=cid)

    payload = json.loads(recording_redis.published[0][1])
    assert payload["conversation_id"] == str(cid)
