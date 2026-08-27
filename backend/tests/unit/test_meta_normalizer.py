"""Normalizer correctness against Meta-shaped payloads."""

from app.integrations.meta.normalizer import normalize_webhook


def _envelope(value: dict) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": value}]}],
    }


def test_text_message_normalized() -> None:
    payload = _envelope(
        {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": "PN1"},
            "contacts": [{"profile": {"name": "Alice"}, "wa_id": "5491150000001"}],
            "messages": [
                {
                    "from": "5491150000001",
                    "id": "wamid.TEXT",
                    "timestamp": "1714939200",
                    "text": {"body": "hello"},
                    "type": "text",
                }
            ],
        }
    )
    out = normalize_webhook(payload)
    assert len(out.inbound_messages) == 1
    msg = out.inbound_messages[0]
    assert msg.meta_message_id == "wamid.TEXT"
    assert msg.from_phone == "5491150000001"
    assert msg.to_phone_number_id == "PN1"
    assert msg.message_type == "text"
    assert msg.text == "hello"
    assert msg.contact_name == "Alice"
    assert msg.media_id is None


def test_media_message_normalized() -> None:
    payload = _envelope(
        {
            "metadata": {"phone_number_id": "PN1"},
            "messages": [
                {
                    "from": "111",
                    "id": "wamid.IMG",
                    "timestamp": "1714939200",
                    "type": "image",
                    "image": {"id": "media-1", "mime_type": "image/jpeg", "caption": "cat"},
                }
            ],
        }
    )
    out = normalize_webhook(payload)
    assert len(out.inbound_messages) == 1
    msg = out.inbound_messages[0]
    assert msg.message_type == "image"
    assert msg.media_id == "media-1"
    assert msg.media_mime_type == "image/jpeg"
    assert msg.caption == "cat"
    assert msg.text is None


def test_interactive_button_reply_extracts_title() -> None:
    payload = _envelope(
        {
            "metadata": {"phone_number_id": "PN1"},
            "messages": [
                {
                    "from": "111",
                    "id": "wamid.INT",
                    "timestamp": "1714939200",
                    "type": "interactive",
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {"id": "btn-yes", "title": "Yes"},
                    },
                }
            ],
        }
    )
    out = normalize_webhook(payload)
    assert out.inbound_messages[0].text == "Yes"


def test_status_failed_extracts_error() -> None:
    payload = _envelope(
        {
            "metadata": {"phone_number_id": "PN1"},
            "statuses": [
                {
                    "id": "wamid.OUT",
                    "recipient_id": "111",
                    "status": "failed",
                    "timestamp": "1714939200",
                    "errors": [{"code": 131026, "message": "Receiver is incapable"}],
                }
            ],
        }
    )
    out = normalize_webhook(payload)
    assert len(out.status_updates) == 1
    s = out.status_updates[0]
    assert s.status == "failed"
    assert s.error_code == 131026
    assert s.error_message == "Receiver is incapable"


def test_missing_id_skipped() -> None:
    payload = _envelope(
        {
            "metadata": {"phone_number_id": "PN1"},
            "messages": [{"from": "111", "type": "text", "text": {"body": "no id"}}],
        }
    )
    out = normalize_webhook(payload)
    assert out.inbound_messages == []


def test_empty_envelope_returns_empty() -> None:
    out = normalize_webhook({})
    assert out.inbound_messages == []
    assert out.status_updates == []


def test_multiple_entries_and_changes_flattened() -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "PN1"},
                            "messages": [
                                {
                                    "from": "1",
                                    "id": "a",
                                    "timestamp": "1",
                                    "type": "text",
                                    "text": {"body": "x"},
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "PN1"},
                            "messages": [
                                {
                                    "from": "2",
                                    "id": "b",
                                    "timestamp": "2",
                                    "type": "text",
                                    "text": {"body": "y"},
                                }
                            ],
                        }
                    }
                ]
            },
        ],
    }
    out = normalize_webhook(payload)
    assert {m.meta_message_id for m in out.inbound_messages} == {"a", "b"}
