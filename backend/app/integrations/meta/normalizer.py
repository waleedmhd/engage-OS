"""Convert raw Meta WhatsApp Cloud API webhook payloads into normalized events.

Meta sends a single envelope that may contain multiple `entry[].changes[]`,
each of which can hold inbound messages and/or delivery-status updates. The
normalizer flattens all of them into typed lists while tolerating partial /
unknown shapes (any field can be absent in real traffic).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.integrations.meta.schemas import (
    NormalizedContactCard,
    NormalizedInboundMessage,
    NormalizedStatusUpdate,
    NormalizedWebhook,
)

logger = get_logger(__name__)


def _ts_to_dt(ts: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(tz=UTC)


def _extract_text(message: dict[str, Any]) -> str | None:
    mtype = message.get("type")
    if mtype == "text":
        return (message.get("text") or {}).get("body")
    if mtype == "button":
        return (message.get("button") or {}).get("text")
    if mtype == "interactive":
        interactive = message.get("interactive") or {}
        if "button_reply" in interactive:
            return (interactive["button_reply"] or {}).get("title")
        if "list_reply" in interactive:
            return (interactive["list_reply"] or {}).get("title")
    if mtype == "reaction":
        return (message.get("reaction") or {}).get("emoji")
    return None


_MEDIA_KEYS = ("image", "audio", "video", "document", "sticker")


def _extract_media(message: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Return (media_id, mime_type, caption) for media messages, else (None, None, None)."""
    for key in _MEDIA_KEYS:
        if key in message and isinstance(message[key], dict):
            blob = message[key]
            return blob.get("id"), blob.get("mime_type"), blob.get("caption")
    return None, None, None


def _extract_contact_card(message: dict[str, Any]) -> NormalizedContactCard | None:
    """Extract contact card data from a contacts message type."""
    contacts = message.get("contacts", [])
    if not contacts:
        return None
    first = contacts[0] or {}
    name = (first.get("name") or {}).get("formatted_name") or \
           (first.get("name") or {}).get("first_name")
    phones_data = first.get("phones", [])
    phones = [p.get("phone") for p in phones_data if p.get("phone")]
    if name or phones:
        return NormalizedContactCard(name=name, phones=phones)
    return None


def normalize_webhook(payload: dict[str, Any]) -> NormalizedWebhook:
    inbound: list[NormalizedInboundMessage] = []
    statuses: list[NormalizedStatusUpdate] = []

    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            phone_number_id = str(metadata.get("phone_number_id") or "")

            contacts_by_waid: dict[str, str] = {}
            for contact in value.get("contacts", []) or []:
                wa_id = contact.get("wa_id")
                profile_name = (contact.get("profile") or {}).get("name")
                if wa_id and profile_name:
                    contacts_by_waid[wa_id] = profile_name

            for msg in value.get("messages", []) or []:
                meta_id = msg.get("id")
                if not meta_id:
                    logger.warning("meta_inbound_missing_id", message_keys=list(msg.keys()))
                    continue
                from_phone = str(msg.get("from") or "")
                mtype = str(msg.get("type") or "unknown")
                media_id, mime, caption = _extract_media(msg)
                # Reply/reaction context: Meta sends the referenced message ID in
                # ``context.id`` for replies, ``reaction.message_id`` for reactions.
                context_id = (msg.get("context") or {}).get("id")
                if not context_id:
                    context_id = (msg.get("reaction") or {}).get("message_id")
                # Contact cards: shared contact vcard.
                contact_card = _extract_contact_card(msg) if mtype == "contacts" else None
                inbound.append(
                    NormalizedInboundMessage(
                        meta_message_id=str(meta_id),
                        from_phone=from_phone,
                        to_phone_number_id=phone_number_id,
                        timestamp=_ts_to_dt(msg.get("timestamp")),
                        message_type=mtype,
                        text=_extract_text(msg),
                        media_id=media_id,
                        media_mime_type=mime,
                        caption=caption,
                        contact_name=contacts_by_waid.get(from_phone),
                        context_message_id=str(context_id) if context_id else None,
                        contact_card=contact_card,
                        raw=msg,
                    )
                )

            for status in value.get("statuses", []) or []:
                meta_id = status.get("id")
                if not meta_id:
                    continue
                errors = status.get("errors") or []
                error_code = None
                error_message = None
                if errors and isinstance(errors[0], dict):
                    error_code = errors[0].get("code")
                    error_message = errors[0].get("message") or errors[0].get("title")
                pricing = (status.get("pricing") or {}).get("category")
                statuses.append(
                    NormalizedStatusUpdate(
                        meta_message_id=str(meta_id),
                        status=str(status.get("status") or "unknown").lower(),
                        timestamp=_ts_to_dt(status.get("timestamp")),
                        recipient_phone=status.get("recipient_id"),
                        error_code=int(error_code) if isinstance(error_code, int) else None,
                        error_message=error_message,
                        pricing_category=pricing,
                        raw=status,
                    )
                )

    return NormalizedWebhook(inbound_messages=inbound, status_updates=statuses)
