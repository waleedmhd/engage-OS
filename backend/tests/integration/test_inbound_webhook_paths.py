"""Integration coverage for process_inbound_webhook_task / _persist_inbound
across payload variants, plus delivery-status callbacks.

Drives the real sync task against committed Postgres + Redis (Meta/AI not
needed — AI dispatch is patched out and asserted)."""
from __future__ import annotations

import uuid

import pytest

from tests.factories import make_contact, make_conversation


def _inbound(meta_id, from_phone="16175559999", mtype="text", body="hi there"):
    msg = {
        "id": meta_id,
        "from": from_phone,
        "type": mtype,
        "timestamp": "1700000000",
    }
    if mtype == "text":
        msg["text"] = {"body": body}
    value = {
        "metadata": {"display_phone_number": "16505551111"},
        "messages": [msg],
    }
    return {"entry": [{"changes": [{"value": value}]}]}


def _status(meta_id, status):
    value = {"statuses": [{"id": meta_id, "status": status}]}
    return {"entry": [{"changes": [{"value": value}]}]}


@pytest.fixture
def no_ai(monkeypatch):
    captured = []
    from app.modules.ai import tasks as ai_tasks

    monkeypatch.setattr(
        ai_tasks.request_ai_reply_task, "delay",
        lambda *a, **k: captured.append(a),
    )
    return captured


def test_new_contact_text_inbound_enqueues_ai(committed_db, redis_client, no_ai):
    from app.modules.contacts.models import Contact
    from app.modules.conversations.models import Conversation
    from app.modules.messaging.tasks import process_inbound_webhook_task

    process_inbound_webhook_task.run(_inbound("wamid.it.1", "16175550100"))

    committed_db.expire_all()
    c = committed_db.query(Contact).filter_by(phone="16175550100").one()
    conv = committed_db.query(Conversation).filter_by(contact_id=c.id).one()
    assert conv.state == "AI_ACTIVE"
    assert conv.last_message_at is not None, (
        "inbound must bump last_message_at so the inbox floats the conversation to the top"
    )

    # Auto-tagging: contact must get the "Inbound Contact" tag.
    from app.modules.categorization.models import ContactTag, Tag
    inbound_tag = committed_db.query(Tag).filter_by(name="Inbound Contact").one()
    ct = (
        committed_db.query(ContactTag)
        .filter_by(contact_id=c.id, tag_id=inbound_tag.id)
        .one_or_none()
    )
    assert ct is not None, (
        "contact must be auto-tagged 'Inbound Contact' on first inbound message"
    )

    assert no_ai, "AI reply task must be enqueued (B-10)"


def test_inbound_does_not_retag_existing_contact(committed_db, redis_client, no_ai):
    """A contact who already has a conversation must NOT be auto-tagged
    'Inbound Contact' on subsequent inbound messages — the tag is for
    first-contact discovery only."""
    from app.modules.categorization.models import ContactTag, Tag
    from app.modules.conversations.models import Conversation
    from app.modules.messaging.tasks import process_inbound_webhook_task

    contact = make_contact(committed_db, phone="16175550199", name="Returning Customer")
    make_conversation(committed_db, contact=contact, state="CLOSED")
    committed_db.commit()

    # Ensure the tag exists (would have been seeded or created on first use).
    inbound_tag = committed_db.query(Tag).filter_by(name="Inbound Contact").one_or_none()
    if inbound_tag is None:
        inbound_tag = Tag(id=uuid.uuid4(), name="Inbound Contact")
        committed_db.add(inbound_tag)
        committed_db.commit()

    process_inbound_webhook_task.run(_inbound("wamid.ret.1", "16175550199"))

    committed_db.expire_all()
    ct = (
        committed_db.query(ContactTag)
        .filter_by(contact_id=contact.id, tag_id=inbound_tag.id)
        .one_or_none()
    )
    assert ct is None, (
        "contact with existing conversation must NOT be auto-tagged 'Inbound Contact'"
    )

    convs = (
        committed_db.query(Conversation)
        .filter_by(contact_id=contact.id)
        .all()
    )
    assert len(convs) >= 1


def test_inbound_canonicalizes_phone_and_matches_existing_contact(
    committed_db, redis_client, no_ai
):
    """Regression: the inbound lookup canonicalizes the sender phone before
    matching, so a formatted/`+`-prefixed `from` still resolves to the saved
    (digits-only) contact — no duplicate, name-less contact, no new chat.

    Previously the exact-string lookup compared the raw `from` against the
    stored phone, missed on any format difference, and spawned an orphan
    contact so the reply opened a new chat showing only the number."""
    from app.modules.contacts.models import Contact
    from app.modules.conversations.models import Conversation
    from app.modules.messaging.tasks import process_inbound_webhook_task

    # Stored canonical (as the create/CSV paths + migration now guarantee).
    contact = make_contact(
        committed_db, phone="16175550200", name="Saved Customer"
    )
    committed_db.commit()

    # Defensive: an inbound `from` carrying a '+' must still match.
    process_inbound_webhook_task.run(_inbound("wamid.plus.1", "+16175550200"))

    committed_db.expire_all()
    contacts = (
        committed_db.query(Contact)
        .filter(Contact.phone.in_(["+16175550200", "16175550200"]))
        .all()
    )
    assert len(contacts) == 1
    assert contacts[0].id == contact.id
    assert contacts[0].name == "Saved Customer"
    convs = (
        committed_db.query(Conversation).filter_by(contact_id=contact.id).all()
    )
    assert len(convs) == 1


def test_image_inbound_persists_placeholder(committed_db, redis_client, no_ai):
    from app.modules.messaging.tasks import process_inbound_webhook_task

    process_inbound_webhook_task.run(
        _inbound("wamid.it.img", "16175550101", mtype="image")
    )
    from app.modules.contacts.models import Contact
    from app.modules.messaging.models import Message

    committed_db.expire_all()
    c = committed_db.query(Contact).filter_by(phone="16175550101").one()
    msgs = committed_db.query(Message).all()
    assert any(m.content == "[image]" for m in msgs)


def test_ai_disabled_conversation_goes_human(committed_db, redis_client, no_ai):
    from app.modules.conversations.models import Conversation
    from app.modules.messaging.tasks import process_inbound_webhook_task

    contact = make_contact(committed_db, phone="16175550102")
    make_conversation(
        committed_db, contact=contact, state="NEW", ai_enabled=False
    )
    committed_db.commit()

    process_inbound_webhook_task.run(_inbound("wamid.it.2", "16175550102"))

    committed_db.expire_all()
    conv = (
        committed_db.query(Conversation)
        .filter_by(contact_id=contact.id)
        .one()
    )
    assert conv.state == "HUMAN_ASSIGNED"
    assert not no_ai


def test_missing_from_is_noop(committed_db, redis_client, no_ai):
    from app.modules.messaging.tasks import process_inbound_webhook_task

    value = {
        "metadata": {},
        "messages": [
            {
                "id": "wamid.nofrom",
                "type": "text",
                "text": {"body": "x"},
                "timestamp": "1700000000",
            }
        ],
    }
    payload = {"entry": [{"changes": [{"value": value}]}]}
    # Must not raise.
    process_inbound_webhook_task.run(payload)


def test_status_updates_apply(committed_db, redis_client):
    from app.modules.messaging.models import Message
    from app.modules.messaging.tasks import process_inbound_webhook_task

    contact = make_contact(committed_db, phone="16175550103")
    conv = make_conversation(committed_db, contact=contact, state="AI_ACTIVE")
    m = Message(
        conversation_id=conv.id, direction="outbound", sender_type="system",
        content="hi", meta_message_id="wamid.st.1", delivery_status="sent",
    )
    committed_db.add(m)
    committed_db.commit()

    process_inbound_webhook_task.run(_status("wamid.st.1", "delivered"))
    committed_db.expire_all()
    assert committed_db.get(Message, m.id).delivery_status == "delivered"

    # Out-of-order 'sent' after 'delivered' must NOT regress (B-4).
    process_inbound_webhook_task.run(_status("wamid.st.1", "sent"))
    committed_db.expire_all()
    assert committed_db.get(Message, m.id).delivery_status == "delivered"


# ---------------------------------- P2.4: NEW→AI_ACTIVE entry transition (§4.2)

@pytest.fixture
def capture_events():
    """Capture in-process domain events without the structlog/redis path."""
    from app.core import events

    seen: list[tuple[str, dict]] = []

    def _h(event_name, **payload):
        seen.append((event_name, payload))

    events.subscribe("conversation.first_activated", _h)
    yield seen
    events.unsubscribe("conversation.first_activated", _h)


def test_new_ai_enabled_inbound_emits_first_activated(
    committed_db, redis_client, no_ai, capture_events
):
    """DSD §4.2 entry transition fires AND emits FIRST_ACTIVATED (Conv-I5)
    on the messaging task path (was previously dropped here)."""
    from app.modules.contacts.models import Contact
    from app.modules.conversations.models import Conversation
    from app.modules.messaging.tasks import process_inbound_webhook_task

    process_inbound_webhook_task.run(_inbound("wamid.fa.1", "16175550110"))

    committed_db.expire_all()
    c = committed_db.query(Contact).filter_by(phone="16175550110").one()
    conv = committed_db.query(Conversation).filter_by(contact_id=c.id).one()
    assert conv.state == "AI_ACTIVE"

    names = [n for n, _ in capture_events]
    assert "conversation.first_activated" in names
    payload = next(p for n, p in capture_events if n == "conversation.first_activated")
    assert payload["conversation_id"] == str(conv.id)
    assert payload["to_state"] == "AI_ACTIVE"


def test_ai_disabled_inbound_does_not_emit_first_activated(
    committed_db, redis_client, no_ai, capture_events
):
    """ai_enabled=False NEW conversation goes HUMAN_ASSIGNED — no AI, and
    no FIRST_ACTIVATED event (Meta-I7 + Conv-I5 negative case)."""
    from app.modules.messaging.tasks import process_inbound_webhook_task

    contact = make_contact(committed_db, phone="16175550111")
    make_conversation(
        committed_db, contact=contact, state="NEW", ai_enabled=False
    )
    committed_db.commit()

    process_inbound_webhook_task.run(_inbound("wamid.fa.2", "16175550111"))

    assert "conversation.first_activated" not in [n for n, _ in capture_events]
    assert not no_ai


# ------------------------------------------------- categorization async

@pytest.mark.asyncio
async def test_categorization_approve_reject_async(async_pg_session):
    import uuid as _uuid

    from app.modules.auth.models import User
    from app.modules.categorization.models import TagSuggestion
    from app.modules.categorization.service import CategorizationService
    from app.modules.contacts.models import Contact

    reviewer = User(
        id=_uuid.uuid4(), email=f"rev-{_uuid.uuid4().hex[:6]}@example.com",
        name="Rev", hashed_password="$2b$12$" + "a" * 53,
        role="admin", is_active=True,
    )
    async_pg_session.add(reviewer)
    contact = Contact(
        id=_uuid.uuid4(), phone="+15550009999", name="Tagged",
        status="active", marketing_opt_out=False,
    )
    async_pg_session.add(contact)
    await async_pg_session.flush()

    s1 = CategorizationService.create_suggestion_sync  # sync staticmethod
    # Use the sync path bridged onto the async connection is not valid;
    # instead create a TagSuggestion via async ORM directly through a tag.
    from app.modules.categorization.models import Tag

    tag = Tag(id=_uuid.uuid4(), name=f"t-{_uuid.uuid4().hex[:6]}")
    async_pg_session.add(tag)
    await async_pg_session.flush()
    sugg = TagSuggestion(
        id=_uuid.uuid4(), contact_id=contact.id, tag_id=tag.id,
        confidence=0.9, status="pending",
    )
    async_pg_session.add(sugg)
    await async_pg_session.flush()

    svc = CategorizationService(async_pg_session)
    tags = await svc.list_tags()
    assert any(t.id == tag.id for t in tags)

    items, total = await svc.list_suggestions(
        status="pending", contact_id=contact.id, page=1, page_size=10
    )
    assert total >= 1

    approved = await svc.approve(sugg.id, reviewer_id=reviewer.id)
    assert approved.status in ("approved", "APPROVED")

    links = await svc.list_contact_tags(contact.id)
    assert any(getattr(l, "tag_id", None) == tag.id for l in links)
