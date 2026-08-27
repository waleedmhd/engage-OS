"""Unit tests for MessagingService.start_conversation_with_template.

Covers:
- Creates a new conversation when none exists for the contact.
- Reuses an existing open conversation rather than creating a duplicate.
- Raises ValidationError (400) when the template is not APPROVED.
- Raises NotFoundError (404) when the contact does not exist.
- The persisted message carries template_name / template_language.
- send_outbound_message_task uses send_template (not send_text) when
  message.template_name is set.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.modules.messaging import tasks as tasks_module
from app.modules.messaging.constants import MessageDeliveryStatus
from app.modules.messaging.service import MessagingService

# ------------------------------------------------------------------ helpers

def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.flush = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)
    return session


def _make_contact(contact_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=contact_id or uuid.uuid4(),
        phone="+15551234567",
        name="Test Contact",
    )


def _make_template(
    *,
    template_id: uuid.UUID | None = None,
    status: str = "approved",
    name: str = "hello_world",
    language: str = "en",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=template_id or uuid.uuid4(),
        name=name,
        status=status,
        language=language,
        category="utility",
    )


def _make_conv(conv_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=conv_id or uuid.uuid4())


def _make_service(session) -> tuple[MessagingService, MagicMock, MagicMock, MagicMock, MagicMock]:
    """Return (service, contact_repo_mock, template_repo_mock, conv_repo_mock, msg_repo_mock)."""
    svc = MessagingService(session)

    contact_repo = AsyncMock()
    template_repo = AsyncMock()
    conv_repo = AsyncMock()
    msg_repo = AsyncMock()
    audit = AsyncMock()

    # Patch the repos that start_conversation_with_template instantiates.
    # ContactRepository and TemplateRepository are monkeypatched per-test.
    svc._conv_repo = conv_repo
    svc._msg_repo = msg_repo
    svc._audit = audit

    # ContactRepository and TemplateRepository are constructed inside the method;
    # we monkeypatch them on the svc_module in each test via monkeypatch (done below).
    return svc, contact_repo, template_repo, conv_repo, msg_repo


# ------------------------------------------------------------------ tests

class TestStartConversationWithTemplate:
    """Tests for MessagingService.start_conversation_with_template."""

    @pytest.mark.asyncio
    async def test_creates_new_conversation_when_none_exists(self, monkeypatch):
        """Creates a new conversation when get_open_for_contact returns None."""
        import app.modules.messaging.service as svc_module

        session = _make_session()
        svc, contact_repo, template_repo, conv_repo, msg_repo = _make_service(session)

        contact = _make_contact()
        template = _make_template()
        new_conv = _make_conv()
        new_msg = SimpleNamespace(
            id=uuid.uuid4(),
            template_name=template.name,
            template_language=template.language,
        )

        contact_repo.get_or_404 = AsyncMock(return_value=contact)
        template_repo.get_or_404 = AsyncMock(return_value=template)
        conv_repo.get_open_for_contact = AsyncMock(return_value=None)
        conv_repo.create_for_contact = AsyncMock(return_value=new_conv)
        msg_repo.create = AsyncMock(return_value=new_msg)

        monkeypatch.setattr(svc_module, "ContactRepository", lambda _s: contact_repo)
        monkeypatch.setattr(svc_module, "TemplateRepository", lambda _s: template_repo)

        conv, msg = await svc.start_conversation_with_template(
            contact_id=contact.id,
            template_id=template.id,
            actor_id=uuid.uuid4(),
        )

        conv_repo.create_for_contact.assert_awaited_once_with(contact_id=contact.id)
        assert conv is new_conv
        assert msg.template_name == template.name

    @pytest.mark.asyncio
    async def test_reuses_existing_open_conversation(self, monkeypatch):
        """Reuses get_open_for_contact result — create_for_contact must NOT be called."""
        import app.modules.messaging.service as svc_module

        session = _make_session()
        svc, contact_repo, template_repo, conv_repo, msg_repo = _make_service(session)

        contact = _make_contact()
        template = _make_template()
        existing_conv = _make_conv()
        new_msg = SimpleNamespace(
            id=uuid.uuid4(),
            template_name=template.name,
            template_language=template.language,
        )

        contact_repo.get_or_404 = AsyncMock(return_value=contact)
        template_repo.get_or_404 = AsyncMock(return_value=template)
        conv_repo.get_open_for_contact = AsyncMock(return_value=existing_conv)
        conv_repo.create_for_contact = AsyncMock()
        msg_repo.create = AsyncMock(return_value=new_msg)

        monkeypatch.setattr(svc_module, "ContactRepository", lambda _s: contact_repo)
        monkeypatch.setattr(svc_module, "TemplateRepository", lambda _s: template_repo)

        conv, _ = await svc.start_conversation_with_template(
            contact_id=contact.id,
            template_id=template.id,
            actor_id=uuid.uuid4(),
        )

        conv_repo.create_for_contact.assert_not_awaited()
        assert conv is existing_conv

    @pytest.mark.asyncio
    async def test_raises_validation_error_for_non_approved_template(self, monkeypatch):
        """ValidationError raised when the template status is not 'approved'."""
        import app.modules.messaging.service as svc_module

        session = _make_session()
        svc, contact_repo, template_repo, conv_repo, msg_repo = _make_service(session)

        contact = _make_contact()
        pending_template = _make_template(status="pending")

        contact_repo.get_or_404 = AsyncMock(return_value=contact)
        template_repo.get_or_404 = AsyncMock(return_value=pending_template)

        monkeypatch.setattr(svc_module, "ContactRepository", lambda _s: contact_repo)
        monkeypatch.setattr(svc_module, "TemplateRepository", lambda _s: template_repo)

        with pytest.raises(ValidationError, match="not approved"):
            await svc.start_conversation_with_template(
                contact_id=contact.id,
                template_id=pending_template.id,
                actor_id=uuid.uuid4(),
            )

        # Must not proceed to create a conversation or message.
        conv_repo.get_open_for_contact.assert_not_awaited()
        msg_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_not_found_for_missing_contact(self, monkeypatch):
        """NotFoundError bubbles up when the contact does not exist."""
        import app.modules.messaging.service as svc_module

        session = _make_session()
        svc, contact_repo, template_repo, conv_repo, msg_repo = _make_service(session)

        contact_repo.get_or_404 = AsyncMock(side_effect=NotFoundError("Contact not found"))

        monkeypatch.setattr(svc_module, "ContactRepository", lambda _s: contact_repo)
        monkeypatch.setattr(svc_module, "TemplateRepository", lambda _s: template_repo)

        with pytest.raises(NotFoundError):
            await svc.start_conversation_with_template(
                contact_id=uuid.uuid4(),
                template_id=uuid.uuid4(),
                actor_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_message_carries_template_fields(self, monkeypatch):
        """Message repo is called with template_name and template_language."""
        import app.modules.messaging.service as svc_module

        session = _make_session()
        svc, contact_repo, template_repo, conv_repo, msg_repo = _make_service(session)

        contact = _make_contact()
        template = _make_template(name="order_confirm", language="ar")
        conv = _make_conv()
        new_msg = SimpleNamespace(
            id=uuid.uuid4(),
            template_name=template.name,
            template_language=template.language,
        )

        contact_repo.get_or_404 = AsyncMock(return_value=contact)
        template_repo.get_or_404 = AsyncMock(return_value=template)
        conv_repo.get_open_for_contact = AsyncMock(return_value=None)
        conv_repo.create_for_contact = AsyncMock(return_value=conv)
        msg_repo.create = AsyncMock(return_value=new_msg)

        monkeypatch.setattr(svc_module, "ContactRepository", lambda _s: contact_repo)
        monkeypatch.setattr(svc_module, "TemplateRepository", lambda _s: template_repo)

        await svc.start_conversation_with_template(
            contact_id=contact.id,
            template_id=template.id,
            actor_id=uuid.uuid4(),
        )

        kwargs = msg_repo.create.call_args.kwargs
        assert kwargs["template_name"] == "order_confirm"
        assert kwargs["template_language"] == "ar"


# ------------------------------------------------------------------ send task

class TestSendOutboundTaskTemplateBranch:
    """send_outbound_message_task calls send_template when template_name is set."""

    def _make_patched(self, monkeypatch, template_name: str | None, *, sender_type: str = "agent"):
        from contextlib import contextmanager

        session = MagicMock()

        @contextmanager
        def fake_factory():
            yield session

        repo = MagicMock()
        contact = SimpleNamespace(
            id=uuid.uuid4(), phone="+15551234567", status="active"
        )
        conversation = SimpleNamespace(contact=contact)
        msg = SimpleNamespace(
            id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            delivery_status=MessageDeliveryStatus.QUEUED.value,
            content="hello_world",
            template_name=template_name,
            template_language="en",
            sender_type=sender_type,
            conversation=conversation,
        )
        repo.get_sync.return_value = msg

        monkeypatch.setattr(tasks_module, "redis_healthy", lambda: True)
        monkeypatch.setattr(tasks_module, "sync_session_factory", fake_factory)
        monkeypatch.setattr(tasks_module, "MessageRepository", lambda _s: repo)
        monkeypatch.setattr(
            tasks_module, "_backfill_campaign_recipient_meta_id", lambda *a, **k: None
        )

        fake_client = MagicMock()
        fake_client.send_text.return_value = {"messages": [{"id": "wamid.text"}]}
        fake_client.send_template.return_value = {"messages": [{"id": "wamid.tpl"}]}
        fake_client.__enter__.return_value = fake_client
        fake_client.__exit__.return_value = False

        import app.integrations.meta.client as meta_client_mod
        monkeypatch.setattr(meta_client_mod, "MetaWhatsAppClient", lambda: fake_client)

        return repo, fake_client, msg

    def test_uses_send_template_when_template_name_set(self, monkeypatch):
        """template_name set → client.send_template called, send_text not called."""
        repo, fake_client, msg = self._make_patched(monkeypatch, "hello_world")

        tasks_module.send_outbound_message_task.run(str(msg.id))

        fake_client.send_template.assert_called_once_with(
            to="+15551234567",
            template_name="hello_world",
            language="en",
        )
        fake_client.send_text.assert_not_called()

        kwargs = repo.update_delivery_status_sync.call_args.kwargs
        assert kwargs["new_status"] == MessageDeliveryStatus.SENT
        assert kwargs["meta_message_id"] == "wamid.tpl"

    def test_uses_send_text_when_template_name_absent(self, monkeypatch):
        """template_name is None → client.send_text called (existing behaviour)."""
        repo, fake_client, msg = self._make_patched(monkeypatch, None)

        tasks_module.send_outbound_message_task.run(str(msg.id))

        fake_client.send_text.assert_called_once()
        fake_client.send_template.assert_not_called()

    def test_system_template_send_uses_send_template_without_components(self, monkeypatch):
        """sender_type=system + template_name → send_template called
        WITHOUT body components."""
        repo, fake_client, msg = self._make_patched(
            monkeypatch, "promo_2024", sender_type="system",
        )

        tasks_module.send_outbound_message_task.run(str(msg.id))

        fake_client.send_template.assert_called_once_with(
            to="+15551234567",
            template_name="promo_2024",
            language="en",
        )
        fake_client.send_text.assert_not_called()
        assert repo.update_delivery_status_sync.call_args.kwargs["meta_message_id"] == "wamid.tpl"
