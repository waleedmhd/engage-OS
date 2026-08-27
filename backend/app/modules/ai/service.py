"""AI Orchestrator service + AIEventReadService (DSD §4.3, §4.4, §11, §10).

Coordinates a Claude cascade (Haiku → Sonnet) for an inbound message:
  1. Build the system prompt + messages from conversation + contact context.
  2. Cascade: Haiku 4.5 drafts every turn; Sonnet 4.6 is called for
     escalation, approval, or gray-zone confidence decisions.
  3. Persist the round-trip to ai_events (DSD §5.1, §4.3).
  4. Apply the decision engine (DSD §4.3) — escalate / approval / auto-send /
     low-confidence-guard, plus categorization side-effects.

The orchestrator runs from a synchronous Celery task. The Claude client is
async, so the cascade is bridged via ``asyncio.run``. Everything else (DB,
state transitions, queueing) is sync.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import sqlalchemy as sa
import structlog
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession

from app.core.config import Settings, get_settings
from app.core.events import ConversationEvents, emit_event
from app.core.exceptions import (
    AIProviderError,
    AIProviderTimeoutError,
    ConcurrentModificationError,
)
from app.integrations.claude import ClaudeClient
from app.integrations.claude.client import ClaudeDecision, ClaudeUsage
from app.modules.ai.constants import (
    CONFIDENCE_AUTO_REPLY_THRESHOLD,
    ModelTier,
)
from app.modules.ai.delay import compute_delay
from app.modules.ai.models import AIEvent
from app.modules.ai.prompts import build_messages, build_system_blocks
from app.modules.ai.repository import AIEventRepository
from app.modules.categorization.constants import PREDEFINED_TAGS
from app.modules.categorization.service import CategorizationService
from app.modules.contacts.memory_service import get_memory_text, update_memory_sync
from app.modules.contacts.models import Contact
from app.modules.conversations.constants import ConversationState
from app.modules.conversations.models import Conversation
from app.modules.conversations.repository import ConversationRepository
from app.modules.conversations.state_machine import (
    TRANSITION_EVENTS,
    assert_transition,
)
from app.modules.messaging.constants import (
    MessageDeliveryStatus,
    MessageDirection,
    SenderType,
)
from app.modules.messaging.models import Message
from app.modules.settings.constants import (
    SETTING_AI_AUTO_SEND_ENABLED,
    SETTING_AI_BUSINESS_CARD_MEDIA_ID,
    SETTING_AI_KILL_SWITCH,
    SETTING_AI_RESPONSE_GENERATION_ENABLED,
    SETTING_AI_TAG_SUGGESTIONS_ENABLED,
)

logger = structlog.get_logger(__name__)

DecisionAction = Literal["auto_send", "approval", "escalate", "noop"]

_ALLOWED_ACTIONS = ("reply", "tag", "escalate")


@dataclass
class Decision:
    """Outcome of the DSD §4.3 decision engine for a single AI response."""

    action: DecisionAction
    delay_seconds: int | None = None
    draft_message_id: uuid.UUID | None = None
    tag_suggestion_ids: list[uuid.UUID] = field(default_factory=list)
    reason: str | None = None
    msg_type: str | None = None
    send_contact_card: bool = False
    send_business_card_image: bool = False


class AIOrchestrator:
    """Two-tier Claude cascade (feasibility study §5):

    1. Haiku 4.5 drafts every turn (cheap, fast, cached prefix).
    2. If the draft needs judgement (escalate / approval / gray-zone
       confidence), Sonnet 4.6 produces the authoritative decision.

    Any provider failure → conservative human fallback (DSD §11).
    """

    def __init__(
        self,
        session: SyncSession,
        client: ClaudeClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._client = client or ClaudeClient(
            self._settings, tag_taxonomy=PREDEFINED_TAGS
        )
        self._events = AIEventRepository(session)  # type: ignore[arg-type]
        self._conversations = ConversationRepository(session)  # type: ignore[arg-type]

    # ------------------------------------------------------------------ public

    def process_inbound(
        self,
        conversation_id: uuid.UUID,
        *,
        incoming_message: str,
    ) -> Decision:
        """End-to-end: serialize → cascade route → persist event → decide → apply.

        Returns the Decision so the calling Celery task can enqueue follow-up
        work (e.g. delayed send). Raises AIProviderError/AIProviderTimeoutError
        for the caller's retry policy. On retryable failure the AIEvent error
        row is persisted before the exception propagates.
        """
        conv = self._session.get(Conversation, conversation_id)
        if conv is None:
            raise ConcurrentModificationError(
                f"conversation_not_found:{conversation_id}"
            )

        contact = self._session.get(Contact, conv.contact_id)

        # Master kill-switch with test-number exceptions: if the kill switch is
        # ON and this contact's phone isn't in the admin-configured test list,
        # skip the Claude cascade entirely — no tags, no reply.
        kill = False
        test_numbers: list[str] = []
        try:
            from app.modules.settings.repository import (  # lazy — cross-module
                get_bool_setting_sync,
                get_test_numbers_sync,
            )

            kill = get_bool_setting_sync(
                self._session, SETTING_AI_KILL_SWITCH, default=False
            )
            test_numbers = get_test_numbers_sync(self._session)
        except Exception:
            logger.warning("ai_settings_read_failed_fail_open", conversation_id=str(conv.id))
        contact_phone = (contact.phone or "") if contact else ""
        ai_blocked = kill and contact_phone not in test_numbers
        if ai_blocked:
            logger.info(
                "ai_blocked_by_kill_switch",
                conversation_id=str(conv.id),
                contact_phone=contact_phone,
            )
            return Decision(action="noop", reason="ai_kill_switch_blocked")

        # Ensure contact.information is populated — extract key facts from
        # the full cross-conversation chat history once, then reference it
        # on every subsequent turn. Never overwrites an existing value.
        if contact is not None and not contact.information:
            self._ensure_contact_information(contact)

        # Load the client memory from the Railway volume so the AI has full
        # accumulated context beyond what fits in the message-history window.
        client_memory: str | None = None
        if contact is not None and self._settings.AI_CLIENT_MEMORY_ENABLED:
            client_memory = get_memory_text(contact.id)

        # Build prompt context (includes full chat history + memory + contact).
        system_blocks = build_system_blocks()
        messages = self._build_ai_messages(
            conv, contact, incoming_message, client_memory=client_memory
        )
        request_log = self._serialize_for_logging(
            conv, contact, incoming_message, client_memory=client_memory
        )

        try:
            response, usage, latency_ms = asyncio.run(
                self._cascade_route(system_blocks, messages)
            )
        except (AIProviderTimeoutError, AIProviderError) as exc:
            self._events.record_event_sync(
                conversation_id=conv.id,
                request=request_log,
                response={},
                intent=None,
                confidence=None,
                latency_ms=None,
                cost_estimate=self._cost_for_failure(),
                error=f"{exc.code}:{exc.message}",
            )
            self._session.commit()
            raise

        cost = self._cost_for_usage(usage)
        self._events.record_event_sync(
            conversation_id=conv.id,
            request=request_log,
            response={
                "reply": response.reply,
                "confidence": response.confidence,
                "intent": response.intent,
                "suggested_tags": response.suggested_tags,
                "requires_approval": response.requires_approval,
                "escalate": response.escalate,
                "send_contact_card": response.send_contact_card,
                "send_business_card_image": response.send_business_card_image,
                "usage": usage.model_dump(),
            },
            intent=response.intent or None,
            confidence=response.confidence,
            latency_ms=latency_ms,
            cost_estimate=cost,
            error=None,
        )

        decision = self._decide(conv, contact, response)

        # Update the client memory on the Railway volume so subsequent turns
        # carry forward context that would otherwise scroll out of the
        # message-history window. Failure is non-fatal — the next turn will
        # retry with whatever messages are still in the window.
        if (
            contact is not None
            and response.reply.strip()
            and self._settings.AI_CLIENT_MEMORY_ENABLED
        ):
            try:
                history = self._load_history(conv.id)
                update_memory_sync(
                    self._session,
                    contact.id,
                    messages=history,
                    ai_reply=response.reply,
                    settings=self._settings,
                )
            except Exception:
                logger.warning(
                    "memory_update_failed",
                    contact_id=str(contact.id),
                    conversation_id=str(conv.id),
                    exc_info=True,
                )

        self._session.commit()
        return decision

    def assign_human(
        self,
        conversation_id: uuid.UUID,
        *,
        reason: str,
    ) -> None:
        """DSD §11 fallback: take a conversation out of AI handling.

        Used by the Celery task after retries are exhausted. Idempotent — if
        the conversation is already past AI handling we short-circuit.
        """
        conv = self._session.get(Conversation, conversation_id)
        if conv is None:
            return
        current = ConversationState(conv.state)
        target = ConversationState.HUMAN_ASSIGNED
        if current == target or current == ConversationState.CLOSED:
            return
        try:
            assert_transition(current, target)
        except Exception:
            logger.warning(
                "assign_human_illegal_transition",
                conversation_id=str(conversation_id),
                from_state=current.value,
                reason=reason,
            )
            return
        rows = self._conversations.update_state_sync(
            conversation_id=conv.id,
            expected_state=current,
            new_state=target,
        )
        if rows == 0:
            raise ConcurrentModificationError(
                f"conversation {conv.id} state changed during assign_human"
            )
        self._session.execute(
            sa.update(Conversation)
            .where(Conversation.id == conv.id)
            .values(ai_enabled=False)
        )
        self._session.commit()
        emit_event(
            ConversationEvents.ESCALATED,
            conversation_id=str(conv.id),
            reason=reason,
            from_state=current.value,
            to_state=target.value,
        )

    # ----------------------------------------------------------- cascade router

    async def _cascade_route(
        self,
        system_blocks: list[dict[str, Any]],
        messages: list[dict[str, Any]],
    ) -> tuple[ClaudeDecision, ClaudeUsage, int]:
        """Cascade: Haiku first → Sonnet escalation if needed.

        Always calls ``aclose()`` in finally to prevent SDK connection leaks
        (architectural invariant #12).
        """
        try:
            # ------ Tier 1: Haiku (bulk) ------
            response, usage, latency = await self._client.propose_reply(
                system_blocks=system_blocks,
                messages=messages,
                model=self._settings.AI_MODEL_BULK,
            )
            logger.info(
                "ai_decision",
                tier=ModelTier.BULK,
                model=self._settings.AI_MODEL_BULK,
                confidence=response.confidence,
                escalate=response.escalate,
            )

            if not self._needs_escalation(response):
                return response, usage, latency

            # ------ Tier 2: Sonnet (escalation) ------
            logger.info(
                "cascade_escalating_to_sonnet",
                haiku_confidence=response.confidence,
                haiku_intent=response.intent,
            )
            response2, usage2, latency2 = await self._client.propose_reply(
                system_blocks=system_blocks,
                messages=messages,
                model=self._settings.AI_MODEL_ESCALATION,
            )
            logger.info(
                "ai_decision",
                tier=ModelTier.ESCALATION,
                model=self._settings.AI_MODEL_ESCALATION,
                confidence=response2.confidence,
                escalate=response2.escalate,
            )
            return response2, usage2, latency + latency2
        finally:
            await self._client.aclose()

    # ------------------------------------------------------- prompt / messages

    def _build_ai_messages(
        self,
        conversation: Conversation,
        contact: Contact | None,
        incoming_message: str,
        *,
        client_memory: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build Anthropic-format messages from conversation history.

        Includes the full chat history (all messages, chronologically), the
        client memory summary (accumulated context from past conversations),
        contact metadata, and the incoming message.
        """
        from app.modules.ai.schemas import AIRequest

        contact_context: dict[str, Any] = {}
        if contact is not None:
            contact_context = {
                "name": contact.name,
                "phone": contact.phone,
                "company": contact.company,
                "status": contact.status,
                "information": contact.information,
            }

        history = self._load_history(conversation.id)

        request = AIRequest(
            conversation_id=str(conversation.id),
            contact_context=contact_context,
            message_history=history,
            incoming_message=incoming_message,
            allowed_actions=list(_ALLOWED_ACTIONS),
            client_memory=client_memory,
            metadata={
                "app_version": self._settings.APP_VERSION,
                "trace_id": str(uuid.uuid4()),
            },
        )
        return build_messages(request)

    def _load_history(self, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
        """Load the full chat history for the conversation.

        The client memory file carries accumulated context for anything that
        scrolls beyond this window, so the AI always has the full picture.
        """
        limit = self._settings.AI_HISTORY_MESSAGE_LIMIT
        rows = self._session.execute(
            sa.select(
                Message.id,
                Message.direction,
                Message.sender_type,
                Message.content,
                Message.created_at,
            )
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        ).all()
        # Reverse to chronological order for the LLM context window.
        history: list[dict[str, Any]] = []
        for row in reversed(rows):
            role = "user" if row.direction == MessageDirection.INBOUND else "assistant"
            history.append(
                {
                    "id": str(row.id),
                    "role": role,
                    "sender_type": str(row.sender_type),
                    "content": row.content,
                    "created_at": row.created_at.isoformat()
                    if row.created_at
                    else None,
                }
            )
        return history

    # ------------------------------------------------ contact information extraction

    def _ensure_contact_information(self, contact: Contact) -> None:
        """Populate ``contact.information`` once from the full
        cross-conversation chat history.

        When the transcript fits in Haiku's context window the extraction
        is a single call. When it's too large we use a two-tier pipeline:
        Sonnet condenses the transcript first, then Haiku extracts
        structured facts from the condensed version.

        The result is flushed so the conversation agent sees it on this
        same turn. Failure is non-fatal — the next inbound turn will retry.
        """
        if contact.information:
            return

        all_msgs = self._load_all_contact_messages(contact.id)
        if not all_msgs:
            return

        transcript = _format_contact_transcript(all_msgs)

        # Rough token estimate: ~3.5 chars per token for English text.
        # Haiku 4.5 context is 200K; leave headroom for prompt + response.
        estimated_tokens = len(transcript) / 3.5

        if estimated_tokens < 140_000:
            information = asyncio.run(
                _extract_information_direct(transcript, self._settings)
            )
        else:
            logger.info(
                "contact_information_two_tier",
                contact_id=str(contact.id),
                estimated_tokens=int(estimated_tokens),
            )
            information = asyncio.run(
                _extract_information_two_tier(transcript, self._settings)
            )

        if information:
            contact.information = information
            self._session.flush()

    def _load_all_contact_messages(
        self, contact_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Load every message across every conversation for a contact,
        ordered chronologically. Capped at 5000 rows for safety."""
        rows = (
            self._session.execute(
                sa.select(
                    Message.direction,
                    Message.sender_type,
                    Message.content,
                    Message.created_at,
                )
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(Conversation.contact_id == contact_id)
                .order_by(Message.created_at.asc())
                .limit(5000)
            )
            .all()
        )

        return [
            {
                "direction": row.direction,
                "sender_type": str(row.sender_type),
                "content": row.content,
                "created_at": (
                    row.created_at.isoformat() if row.created_at else None
                ),
            }
            for row in rows
        ]

    # ---------------------------------------------------------------- ai messages

    def _serialize_for_logging(
        self,
        conversation: Conversation,
        contact: Contact | None,
        incoming_message: str,
        *,
        client_memory: str | None = None,
    ) -> dict[str, Any]:
        """Serialize the AI round-trip input for ai_events.request JSONB storage."""
        contact_context: dict[str, Any] = {}
        if contact is not None:
            contact_context = {
                "id": str(contact.id),
                "phone": contact.phone,
                "name": contact.name,
                "company": contact.company,
                "status": contact.status,
                "information": contact.information,
                "assigned_agent_id": (
                    str(contact.assigned_agent_id)
                    if contact.assigned_agent_id
                    else None
                ),
            }
        return {
            "conversation_id": str(conversation.id),
            "contact_context": contact_context,
            "message_history": self._load_history(conversation.id),
            "incoming_message": incoming_message,
            "client_memory": client_memory,
            "metadata": {
                "app_version": self._settings.APP_VERSION,
                "trace_id": str(uuid.uuid4()),
            },
        }

    # ----------------------------------------------------- decision engine

    def _decide(
        self,
        conversation: Conversation,
        contact: Contact | None,
        response: ClaudeDecision,
    ) -> Decision:
        """Apply DSD §4.3 rules in order: opt-out → escalate → approval → FAQ → guard.

        Categorization (suggested_tags) runs as a side effect on every branch.
        """
        # 0. Engagement policy §2: opt-out detection runs FIRST, before any
        #    other decision logic. Explicit keywords are caught by the fast-path
        #    in messaging/tasks.py; AI-inferred (implied) opt-outs arrive here.
        if response.detected_opt_out and contact is not None:
            from app.modules.contacts.repository import ContactRepository

            ContactRepository(self._session).set_do_not_contact_sync(  # type: ignore[arg-type]
                contact.id, True
            )
            self._transition(
                conversation,
                target=ConversationState.HUMAN_ASSIGNED,
                actor_type="ai",
                event_reason="opt_out_detected",
            )
            self._session.execute(
                sa.update(Conversation)
                .where(Conversation.id == conversation.id)
                .values(ai_enabled=False)
            )
            return Decision(
                action="escalate",
                tag_suggestion_ids=[],
                reason="opt_out_detected",
            )

        # Runtime feature toggles (fail-open per DSD §11).
        tag_suggestions_on = True
        response_gen_on = True
        try:
            from app.modules.settings.repository import (  # lazy — cross-module
                get_bool_setting_sync,
            )

            tag_suggestions_on = get_bool_setting_sync(
                self._session, SETTING_AI_TAG_SUGGESTIONS_ENABLED, default=True
            )
            response_gen_on = get_bool_setting_sync(
                self._session, SETTING_AI_RESPONSE_GENERATION_ENABLED, default=True
            )
        except Exception:
            logger.warning("ai_feature_toggle_read_failed_fail_open")

        # Persist tag suggestions only when the toggle is on.
        suggestion_ids: list[uuid.UUID] = []
        if tag_suggestions_on and contact is not None and response.suggested_tags:
            for tag_name in response.suggested_tags:
                if not tag_name:
                    continue
                suggestion = CategorizationService.create_suggestion_sync(
                    self._session,
                    contact_id=contact.id,
                    tag_name=tag_name,
                    confidence=response.confidence,
                    reason=response.intent or None,
                )
                suggestion_ids.append(suggestion.id)

        # Resolve non-text message flags from the AI response. Contact card
        # overrides the content format; business card image links a pre-uploaded
        # MediaAsset via the admin-configured setting.
        draft_msg_type: str | None = None
        media_asset_id: uuid.UUID | None = None
        if response.send_contact_card:
            draft_msg_type = "contact"
        if response.send_business_card_image:
            media_asset_id = self._get_business_card_media_id()

        _send_cc = response.send_contact_card
        _send_bc = response.send_business_card_image

        # Response generation toggle: when OFF, skip reply entirely (no draft,
        # no auto-send, no approval — just return tag suggestions if any).
        if not response_gen_on:
            return Decision(
                action="noop",
                tag_suggestion_ids=suggestion_ids,
                reason="response_generation_disabled",
                send_contact_card=_send_cc,
                send_business_card_image=_send_bc,
            )

        # 1. Escalation wins outright (DSD §4.3 Escalation).
        if response.escalate:
            self._transition(
                conversation,
                target=ConversationState.HUMAN_ASSIGNED,
                actor_type="ai",
                event_reason="response_escalate",
            )
            self._session.execute(
                sa.update(Conversation)
                .where(Conversation.id == conversation.id)
                .values(ai_enabled=False)
            )
            return Decision(
                action="escalate",
                tag_suggestion_ids=suggestion_ids,
                reason="response_escalate",
                send_contact_card=_send_cc,
                send_business_card_image=_send_bc,
            )

        # 2. Approval (Qualification — DSD §4.3).
        if response.requires_approval:
            draft = self._create_draft_message(
                conversation_id=conversation.id,
                content=response.reply,
                status=MessageDeliveryStatus.DRAFT,
                msg_type=draft_msg_type,
                media_asset_id=media_asset_id,
            )
            self._transition(
                conversation,
                target=ConversationState.AWAITING_APPROVAL,
                actor_type="ai",
                event_reason="requires_approval",
            )
            return Decision(
                action="approval",
                draft_message_id=draft.id,
                tag_suggestion_ids=suggestion_ids,
                reason="requires_approval",
                msg_type=draft_msg_type,
                send_contact_card=_send_cc,
                send_business_card_image=_send_bc,
            )

        # 3. FAQ auto-send (DSD §4.3): confidence > 0.85 and no escalation.
        if (
            response.confidence > CONFIDENCE_AUTO_REPLY_THRESHOLD
            and response.reply.strip()
        ):
            # Auto-send gate. The master kill-switch is enforced pre-cascade in
            # process_inbound; by the time we reach _decide the contact has
            # already passed that gate (either kill-switch is OFF or the contact
            # is a test number). Here we only check whether auto-send is enabled.
            # Fail-open per DSD §11.
            suppress = False
            try:
                from app.modules.settings.repository import (  # lazy — cross-module
                    get_bool_setting_sync,
                )

                auto = get_bool_setting_sync(
                    self._session, SETTING_AI_AUTO_SEND_ENABLED, default=True
                )
                suppress = not auto
            except Exception:
                logger.warning(
                    "ai_settings_read_failed_fail_open",
                    conversation_id=str(conversation.id),
                )
            if suppress:
                draft = self._create_draft_message(
                    conversation_id=conversation.id,
                    content=response.reply,
                    status=MessageDeliveryStatus.DRAFT,
                    msg_type=draft_msg_type,
                    media_asset_id=media_asset_id,
                )
                self._transition(
                    conversation,
                    target=ConversationState.AWAITING_APPROVAL,
                    actor_type="ai",
                    event_reason="auto_send_suppressed_by_settings",
                )
                return Decision(
                    action="approval",
                    draft_message_id=draft.id,
                    tag_suggestion_ids=suggestion_ids,
                    reason="auto_send_suppressed_by_settings",
                    msg_type=draft_msg_type,
                    send_contact_card=_send_cc,
                send_business_card_image=_send_bc,
                )
            draft = self._create_draft_message(
                conversation_id=conversation.id,
                content=response.reply,
                msg_type=draft_msg_type,
                media_asset_id=media_asset_id,
            )
            delay = compute_delay(response.reply)
            return Decision(
                action="auto_send",
                draft_message_id=draft.id,
                delay_seconds=delay,
                tag_suggestion_ids=suggestion_ids,
                reason="faq_auto_send",
                msg_type=draft_msg_type,
                send_contact_card=_send_cc,
                send_business_card_image=_send_bc,
            )

        # 4. Low-confidence guard: not escalated, not flagged for approval,
        #    not above the auto-send bar — surface for human review rather
        #    than silently dropping the message.
        if response.reply.strip():
            draft = self._create_draft_message(
                conversation_id=conversation.id,
                content=response.reply,
                status=MessageDeliveryStatus.DRAFT,
                msg_type=draft_msg_type,
                media_asset_id=media_asset_id,
            )
            self._transition(
                conversation,
                target=ConversationState.AWAITING_APPROVAL,
                actor_type="ai",
                event_reason="low_confidence",
            )
            return Decision(
                action="approval",
                draft_message_id=draft.id,
                tag_suggestion_ids=suggestion_ids,
                reason="low_confidence",
                msg_type=draft_msg_type,
                send_contact_card=_send_cc,
                send_business_card_image=_send_bc,
            )

        return Decision(
            action="noop",
            tag_suggestion_ids=suggestion_ids,
            send_contact_card=_send_cc,
            send_business_card_image=_send_bc,
        )

    @staticmethod
    def _needs_escalation(d: ClaudeDecision) -> bool:
        """Determine whether Haiku's draft should be re-evaluated by Sonnet."""
        if d.escalate or d.requires_approval:
            return True
        # Gray zone: not confident enough to auto-send, not clearly an
        # escalation → get Sonnet's second opinion.
        return (
            d.confidence >= 0.50
            and d.confidence <= CONFIDENCE_AUTO_REPLY_THRESHOLD
        )

    # ------------------------------------------------------- side-effect ops

    def _get_business_card_media_id(self) -> uuid.UUID | None:
        """Read the admin-configured business card media asset UUID.

        Fails open: any DB or setting error → None (the text reply still
        goes out, just without the attached image).
        """
        try:
            from app.modules.settings.models import AppSetting

            stmt = sa.select(AppSetting).where(
                sa.and_(
                    AppSetting.key == SETTING_AI_BUSINESS_CARD_MEDIA_ID,
                    AppSetting.scope == "global",
                )
            )
            row = self._session.execute(stmt).scalar_one_or_none()
            if row is None or not isinstance(row.value, dict):
                return None
            raw = row.value.get("media_asset_id")
            if raw is None:
                return None
            return uuid.UUID(str(raw))
        except Exception:
            logger.warning(
                "ai_business_card_media_id_read_failed",
                exc_info=True,
            )
            return None

    def _create_draft_message(
        self,
        *,
        conversation_id: uuid.UUID,
        content: str,
        status: MessageDeliveryStatus = MessageDeliveryStatus.QUEUED,
        msg_type: str | None = None,
        media_asset_id: uuid.UUID | None = None,
    ) -> Message:
        """Persist an AI-authored outbound message draft.

        Use status=DRAFT for messages awaiting human approval; status=QUEUED
        for auto-send messages that will be dispatched after a delay.

        When msg_type is "contact", the content is formatted for the dispatch
        task's contact-card parser (Name — phone1, phone2). When
        media_asset_id is set, the MediaAsset is linked to the message so the
        dispatch task uploads and sends it via send_media.
        """
        resolved_content = content
        if msg_type == "contact":
            # Placeholder demo contact — replace with the real persona's number per deployment.
            resolved_content = "Sara Ahmed — +971 50 000 0000"

        message = Message(
            conversation_id=conversation_id,
            direction=MessageDirection.OUTBOUND.value,
            sender_type=SenderType.AI.value,
            content=resolved_content,
            delivery_status=status.value,
        )
        if msg_type:
            message.msg_type = msg_type
        self._session.add(message)
        self._session.flush()

        if media_asset_id is not None:
            from sqlalchemy.orm import undefer

            from app.modules.media.models import MediaAsset

            asset = self._session.get(
                MediaAsset,
                media_asset_id,
                options=[undefer(MediaAsset.file_data)],
            )
            if asset is None:
                logger.warning(
                    "ai_business_card_media_not_found",
                    media_asset_id=str(media_asset_id),
                )
            elif not asset.file_data:
                logger.warning(
                    "ai_business_card_media_no_file_data",
                    media_asset_id=str(media_asset_id),
                    hint="Re-upload the business card image via Admin → Media Upload, then update the ai.business_card_media_id setting to the new asset UUID",
                )
            else:
                asset.message_id = message.id
                logger.info(
                    "ai_linked_business_card_media",
                    message_id=str(message.id),
                    media_asset_id=str(media_asset_id),
                )

        return message

    def _transition(
        self,
        conversation: Conversation,
        *,
        target: ConversationState,
        actor_type: str,
        event_reason: str,
    ) -> None:
        current = ConversationState(conversation.state)
        if current == target:
            return
        assert_transition(current, target)
        rows = self._conversations.update_state_sync(
            conversation_id=conversation.id,
            expected_state=current,
            new_state=target,
        )
        if rows == 0:
            raise ConcurrentModificationError(
                f"conversation {conversation.id} state changed during AI transition"
            )
        event_name = TRANSITION_EVENTS.get(
            (current, target), "conversation.transitioned"
        )
        emit_event(
            event_name,
            conversation_id=str(conversation.id),
            from_state=current.value,
            to_state=target.value,
            actor_type=actor_type,
            reason=event_reason,
        )

    # ------------------------------------------------------------ cost

    def _cost_for_usage(self, usage: ClaudeUsage) -> float:
        """Approximate cost from actual Anthropic token usage.

        Uses Haiku 4.5 pricing as a conservative base ($1.00/M input,
        $5.00/M output). Cache reads are billed at 10% of base input price.
        This is an estimate — the ``ai_events.response`` JSONB column holds
        the raw token counts as ground truth.
        """
        input_cost = usage.input_tokens * (1.0 / 1_000_000)
        cache_read_cost = usage.cache_read_input_tokens * (0.10 / 1_000_000)
        output_cost = usage.output_tokens * (5.0 / 1_000_000)
        return round(input_cost + cache_read_cost + output_cost, 6)

    def _cost_for_failure(self) -> float:
        """Cost estimate for a failed Claude round-trip. Always zero — no
        chargeable work was done."""
        return 0.0


# ==============================================================================
# Contact information extraction — runs once per contact, populates the
# ``information`` column from the full cross-conversation chat history.
# ==============================================================================

_INFORMATION_EXTRACTION_SYSTEM = """\
You extract a structured information dossier about a WhatsApp business contact
from their full chat history. This dossier will be stored in the CRM and
referenced by an AI sales agent in every future conversation with this contact.

Extract ALL key facts from the history. Be thorough — every detail matters for
future interactions. Output ONLY the dossier as plain text, no JSON, no markdown.

Structure your dossier with these sections (use plain headings):

Who They Are
- Name, company, role/position, location, language preference

What They Deal In
- Products they buy, sell, or are interested in
- Brands, models, specs they've mentioned
- Quantities/volumes they deal with

Business Profile
- Budget range mentioned
- Timeline/urgency
- Payment preferences
- How they found us / source of contact

Key Interactions
- Important decisions or commitments made
- Objections or concerns raised
- Negotiation points
- Follow-up commitments

Preferences & Personal Notes
- Communication style preferences
- Personal details shared (family, background, etc.)
- Any sensitivities or things to avoid

Write concisely. Only include facts actually found in the history — don't
invent or assume. If a section has no information, omit it entirely."""

_INFORMATION_EXTRACTION_USER = """\
Here is the full chat history for this contact. Extract all key information
into a structured dossier following the format specified.

Chat history:
{transcript}"""

_INFORMATION_CONDENSE_SYSTEM = """\
You condense long WhatsApp chat histories into a compact, information-dense
transcript that preserves every factual detail. The condensed version will be
used by another AI to extract a structured contact dossier.

Keep:
- All names, companies, products, prices, quantities, locations
- All decisions, commitments, objections, preferences
- All personal details shared by the contact
- All key interaction moments

Drop:
- Greetings, pleasantries, emoji, small talk
- Repeated information
- System messages, delivery confirmations

Output a plain text transcript in chronological order, labeled "Customer:" or
"Agent:". Keep it as short as possible while preserving every fact."""


def _format_contact_transcript(messages: list[dict[str, Any]]) -> str:
    """Format raw message dicts into a compact chronological transcript."""
    lines: list[str] = []
    for m in messages:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        direction = m.get("direction", "")
        label = "Customer" if direction == "inbound" else "Agent"
        ts = m.get("created_at", "") or ""
        date_str = ts[:10] if ts else ""
        prefix = f"[{date_str}]" if date_str else ""
        lines.append(f"{prefix} {label}: {content}")
    return "\n".join(lines)


async def _extract_information_direct(
    transcript: str,
    settings: Settings,
) -> str | None:
    """Call Haiku to extract contact information from a transcript."""
    try:
        client = AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            timeout=60,
        )
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_INFORMATION_EXTRACTION_SYSTEM,
            messages=[{
                "role": "user",
                "content": _INFORMATION_EXTRACTION_USER.format(
                    transcript=transcript
                ),
            }],
        )
        await client.close()
        text = "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", None) == "text"
        )
        return text.strip() or None
    except Exception as exc:
        logger.warning(
            "contact_information_extraction_failed",
            error=str(exc)[:300],
        )
        return None


async def _extract_information_two_tier(
    transcript: str,
    settings: Settings,
) -> str | None:
    """Condense a large transcript with Sonnet first, then extract with Haiku."""
    try:
        # Tier 1: Sonnet condenses the full transcript.
        client = AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            timeout=120,
        )
        condense_response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=_INFORMATION_CONDENSE_SYSTEM,
            messages=[{"role": "user", "content": transcript}],
        )
        condensed = "".join(
            getattr(block, "text", "")
            for block in condense_response.content
            if getattr(block, "type", None) == "text"
        )
        await client.close()

        if not condensed.strip():
            return None

        # Tier 2: Haiku extracts structured facts from the condensed version.
        return await _extract_information_direct(condensed, settings)
    except Exception as exc:
        logger.warning(
            "contact_information_two_tier_failed",
            error=str(exc)[:300],
        )
        return None


# --------------------------------------------------------------------------- #
# Read surface — admin inspection of ai_events                                #
# --------------------------------------------------------------------------- #
class AIEventReadService:
    """Async read-only service for ``ai_events`` (DSD §10 observability).

    Separate from ``AIOrchestrator`` (sync, Celery-owned) so that HTTP
    routers get a clean async session and don't pull in the Claude client.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = AIEventRepository(session)

    async def list_by_conversation(
        self,
        conversation_id: uuid.UUID,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[AIEvent], int]:
        offset = (page - 1) * page_size
        rows, total = await self._repo.list_by_conversation(
            conversation_id, limit=page_size, offset=offset
        )
        return list(rows), total
