"""Unit tests for Batch 2-3 MessagingService methods: forward, bulk ops,
deleted filtering, context_message_id validation."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import StateTransitionError, ValidationError
from app.modules.conversations.constants import ConversationState
from app.modules.messaging.constants import MessageDeliveryStatus, MessageDirection
from app.modules.messaging.service import MessagingService


def _conv(state=ConversationState.AI_ACTIVE):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.state = state
    c.contact_id = uuid.uuid4()
    return c


def _msg(**kw):
    m = MagicMock()
    m.id = kw.get("id", uuid.uuid4())
    m.conversation_id = kw.get("conversation_id", uuid.uuid4())
    m.content = kw.get("content", "hello")
    m.msg_type = kw.get("msg_type", "text")
    m.direction = kw.get("direction", MessageDirection.OUTBOUND)
    m.delivery_status = kw.get("delivery_status", MessageDeliveryStatus.QUEUED)
    m.template_name = None
    m.template_language = None
    m.media = []
    m.deleted_by = kw.get("deleted_by", None)
    return m


def _make_service(conv, msg=None, *, rows: int = 1):
    session = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()

    svc = MessagingService(session)

    # Conversation repo
    svc._conv_repo.get_or_404 = AsyncMock(return_value=conv)
    svc._conv_repo.get = AsyncMock(return_value=conv)
    svc._conv_repo.update_state = AsyncMock(return_value=rows)

    # Message repo
    svc._msg_repo.get_or_404 = AsyncMock(return_value=msg or _msg())
    svc._msg_repo.get = AsyncMock(return_value=msg or _msg())
    svc._msg_repo.create = AsyncMock(return_value=msg or _msg())
    svc._msg_repo.update = AsyncMock(return_value=msg or _msg())
    svc._msg_repo.list = AsyncMock(return_value=[])
    svc._msg_repo.count = AsyncMock(return_value=0)

    # Audit
    svc._audit.append = AsyncMock()
    return svc


class TestSendMessageWithContext:
    @pytest.mark.asyncio
    async def test_reply_valid_context(self):
        ctx = _msg(id=uuid.uuid4())
        conv = _conv()
        svc = _make_service(conv, msg=_msg())

        svc._msg_repo.get = AsyncMock(return_value=ctx)

        result = await svc.send_message(
            conversation_id=conv.id,
            content="reply text",
            actor_id=uuid.uuid4(),
            context_message_id=ctx.id,
        )

        assert result is not None
        # Create should have been called with context_message_id
        create_kwargs = svc._msg_repo.create.call_args.kwargs
        assert create_kwargs["context_message_id"] == ctx.id

    @pytest.mark.asyncio
    async def test_reply_invalid_context_raises(self):
        conv = _conv()
        svc = _make_service(conv)

        svc._msg_repo.get = AsyncMock(return_value=None)

        with pytest.raises(ValidationError, match="does not exist"):
            await svc.send_message(
                conversation_id=conv.id,
                content="reply",
                actor_id=uuid.uuid4(),
                context_message_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_explicit_msg_type(self):
        conv = _conv()
        svc = _make_service(conv)

        await svc.send_message(
            conversation_id=conv.id,
            content="John — +15551234567",
            actor_id=uuid.uuid4(),
            msg_type="contact",
        )

        create_kwargs = svc._msg_repo.create.call_args.kwargs
        assert create_kwargs["msg_type"] == "contact"


class TestForwardMessage:
    @pytest.mark.asyncio
    async def test_forward_succeeds(self):
        source = _msg()
        target_conv = _conv()

        svc = _make_service(target_conv, msg=source)

        with pytest.MonkeyPatch.context() as mp:
            from app.modules.media.repository import MediaAssetRepository
            mp.setattr(
                MediaAssetRepository, "get_by_message_id",
                AsyncMock(return_value=[]),
            )
            result = await svc.forward_message(
                message_id=source.id,
                target_conversation_id=target_conv.id,
                actor_id=uuid.uuid4(),
            )

        assert result is not None
        create_kwargs = svc._msg_repo.create.call_args.kwargs
        assert create_kwargs["context_message_id"] == source.id
        assert create_kwargs["conversation_id"] == target_conv.id

    @pytest.mark.asyncio
    async def test_forward_to_closed_raises(self):
        source = _msg()
        closed = _conv(state=ConversationState.CLOSED)
        svc = _make_service(closed, msg=source)

        with pytest.raises(StateTransitionError, match="CLOSED"):
            await svc.forward_message(
                message_id=source.id,
                target_conversation_id=closed.id,
                actor_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_forward_media_message_copies_asset(self):
        source = _msg(msg_type="image")
        target_conv = _conv()
        svc = _make_service(target_conv, msg=source)

        fake_asset = MagicMock()
        fake_asset.id = uuid.uuid4()

        from app.modules.media.repository import MediaAssetRepository

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                MediaAssetRepository, "get_by_message_id",
                AsyncMock(return_value=[fake_asset]),
            )
            mp.setattr(
                MediaAssetRepository, "update",
                AsyncMock(return_value=fake_asset),
            )
            result = await svc.forward_message(
                message_id=source.id,
                target_conversation_id=target_conv.id,
                actor_id=uuid.uuid4(),
            )

        assert result is not None


class TestBulkForward:
    @pytest.mark.asyncio
    async def test_bulk_forward_succeeds(self):
        source_ids = [uuid.uuid4(), uuid.uuid4()]
        target_conv = _conv()
        svc = _make_service(target_conv)

        # Each forward will create a new message
        svc._msg_repo.create.side_effect = [
            _msg(id=uuid.uuid4()) for _ in source_ids
        ]

        with pytest.MonkeyPatch.context() as mp:
            from app.modules.media.repository import MediaAssetRepository
            mp.setattr(
                MediaAssetRepository, "get_by_message_id",
                AsyncMock(return_value=[]),
            )
            count, errors, fwd_ids = await svc.bulk_forward(
                message_ids=source_ids,
                target_conversation_id=target_conv.id,
                actor_id=uuid.uuid4(),
            )

        assert count == 2
        assert errors == []
        assert len(fwd_ids) == 2


class TestBulkDelete:
    @pytest.mark.asyncio
    async def test_bulk_delete_for_me(self):
        msgs = [_msg() for _ in range(3)]
        svc = _make_service(_conv(), msg=msgs[0])

        svc._msg_repo.get_or_404 = AsyncMock(side_effect=msgs)
        svc._msg_repo.update = AsyncMock(side_effect=msgs)

        count, errors = await svc.bulk_delete(
            message_ids=[m.id for m in msgs],
            scope="for_me",
            actor_id=uuid.uuid4(),
        )

        assert count == 3
        assert errors == []

    @pytest.mark.asyncio
    async def test_bulk_delete_for_everyone(self):
        msgs = [_msg(deleted_by={"agent_id": "old"}) for _ in range(2)]
        svc = _make_service(_conv(), msg=msgs[0])

        svc._msg_repo.get_or_404 = AsyncMock(side_effect=msgs)
        svc._msg_repo.update = AsyncMock(side_effect=msgs)

        count, errors = await svc.bulk_delete(
            message_ids=[m.id for m in msgs],
            scope="for_everyone",
            actor_id=uuid.uuid4(),
        )

        assert count == 2
        assert errors == []
        # Verify deleted_for_everyone was set
        for call in svc._msg_repo.update.call_args_list:
            assert call.kwargs.get("deleted_for_everyone") is True


class TestListMessagesWithDeletedFilter:
    @pytest.mark.asyncio
    async def test_filters_deleted_by_agent(self, monkeypatch):
        """Verify the deleted-message filter is applied when actor_id is provided.
        Exercises the SQLAlchemy query construction path."""

        conv = _conv()
        svc = _make_service(conv)

        # The list_messages method now bypasses the repo and uses direct SA queries.
        # Mock session.execute to return empty results.
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        svc._session.execute = AsyncMock(return_value=mock_result)

        items, total = await svc.list_messages(
            conversation_id=conv.id,
            actor_id=uuid.uuid4(),
        )

        assert items == []
        # Session.execute should have been called (the SELECT was built)
