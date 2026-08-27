"""More targeted coverage: ContactService.import_csv, AuditRepository
filters, conversation inbox enriched query."""
from __future__ import annotations

import uuid

import pytest

from app.modules.contacts.models import Contact
from app.modules.conversations.models import Conversation
from app.modules.messaging.models import Message


@pytest.mark.asyncio
async def test_contact_service_import_csv(async_pg_session):
    from app.modules.contacts.service import ContactService

    svc = ContactService(async_pg_session)

    receipt = await svc.import_csv(
        raw_bytes=(
            b"phone,name,company\n"
            b"+15554440001,Ann,Acme\n"
            b"+15554440002,Ben,BetaCo\n"
            b"+15554440001,Ann Dup,Acme\n"
            b"bad-phone,Eve,Evil\n"
        ),
        actor_id=uuid.uuid4(),
    )
    assert receipt.created + receipt.updated >= 2
    assert receipt.skipped >= 1  # malformed phone row

    # Missing phone column → early-return receipt branch.
    bad = await svc.import_csv(
        raw_bytes=b"name,company\nNoPhone,Acme\n",
        actor_id=uuid.uuid4(),
    )
    assert bad is not None


@pytest.mark.asyncio
async def test_audit_repository_list_logs_filters(async_pg_session):
    from app.modules.audit.repository import AuditRepository

    repo = AuditRepository(async_pg_session)
    entity_id = uuid.uuid4()
    await repo.append(
        actor_type="agent",
        actor_id=uuid.uuid4(),
        action="conversation.assigned",
        entity_type="conversation",
        entity_id=entity_id,
        before_state={"state": "AI_ACTIVE"},
        after_state={"state": "HUMAN_ASSIGNED"},
    )
    await async_pg_session.flush()

    rows = await repo.list_logs(
        entity_type="conversation",
        entity_id=entity_id,
        action="conversation.assigned",
        page=1,
        page_size=10,
    )
    assert len(rows) >= 1


@pytest.mark.asyncio
async def test_conversation_inbox_enriched_query(async_pg_session):
    from app.modules.conversations.repository import ConversationRepository

    contact = Contact(
        id=uuid.uuid4(), phone="+15556660001", name="Inbox",
        status="active", marketing_opt_out=False,
    )
    async_pg_session.add(contact)
    await async_pg_session.flush()
    conv = Conversation(
        id=uuid.uuid4(), contact_id=contact.id, state="AI_ACTIVE",
        ai_enabled=True,
    )
    async_pg_session.add(conv)
    await async_pg_session.flush()
    async_pg_session.add(
        Message(
            id=uuid.uuid4(), conversation_id=conv.id, direction="inbound",
            sender_type="contact", content="hello there",
            meta_message_id=f"wamid.{uuid.uuid4().hex}",
            delivery_status="delivered",
        )
    )
    await async_pg_session.flush()

    repo = ConversationRepository(async_pg_session)
    items, total = await repo.list_inbox(limit=10, offset=0)
    assert total >= 1
    # The conversation we seeded must carry its last-message preview.
    mine = [i for i in items if i["id"] == conv.id]
    assert mine and mine[0]["last_message"] is not None
