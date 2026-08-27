"""Decision engine (AIOrchestrator._decide) — table-driven unit tests.

The orchestrator is tested in isolation: a lightweight fake sync session
(no real DB) stubs out flush/add/execute calls, and a minimal Conversation +
Contact object is supplied. State transitions are verified via the
update_state_sync call count and arguments.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app.integrations.claude.client import ClaudeDecision
from app.modules.ai.constants import CONFIDENCE_AUTO_REPLY_THRESHOLD
from app.modules.ai.service import AIOrchestrator, Decision
from app.modules.conversations.constants import ConversationState
from app.modules.messaging.constants import MessageDeliveryStatus

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

def _fake_conversation(state: ConversationState) -> MagicMock:
    conv = MagicMock()
    conv.id = uuid.uuid4()
    conv.contact_id = uuid.uuid4()
    conv.state = state.value
    return conv


def _fake_contact(conv_id: uuid.UUID | None = None) -> MagicMock:
    contact = MagicMock()
    contact.id = conv_id or uuid.uuid4()
    return contact


def _fake_session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.flush = MagicMock()
    session.execute = MagicMock()
    session.commit = MagicMock()
    return session


def _response(**kwargs) -> ClaudeDecision:
    defaults = dict(
        reply="test reply",
        confidence=0.9,
        intent="test",
        suggested_tags=[],
        requires_approval=False,
        escalate=False,
    )
    defaults.update(kwargs)
    return ClaudeDecision(**defaults)


def _make_orchestrator(session: MagicMock) -> AIOrchestrator:
    from app.core.config import Settings

    settings = Settings(ANTHROPIC_API_KEY="test-key")
    orch = AIOrchestrator(session=session, settings=settings)
    return orch


# ---------------------------------------------------------------------------
# Decision engine — DSD §4.3
# ---------------------------------------------------------------------------

class TestDecisionEngine:
    """Table-driven tests over each DSD §4.3 decision branch."""

    def _decide(
        self, response: ClaudeDecision, state: ConversationState = ConversationState.AI_ACTIVE
    ) -> Decision:
        session = _fake_session()
        orch = _make_orchestrator(session)
        conv = _fake_conversation(state)
        contact = _fake_contact()

        # Stub _create_draft_message so it returns a Message-like mock.
        draft = MagicMock()
        draft.id = uuid.uuid4()
        with patch.object(orch, "_create_draft_message", return_value=draft):
            with patch.object(orch, "_transition") as mock_transition:
                with patch(
                    "app.modules.ai.service.CategorizationService.create_suggestion_sync",
                    return_value=MagicMock(id=uuid.uuid4()),
                ) as mock_suggest:
                    decision = orch._decide(conv, contact, response)
                    self._mock_transition = mock_transition
                    self._mock_suggest = mock_suggest
                    self._draft = draft
        return decision

    # ---- Branch 1: Escalation ----------------------------------------

    def test_escalation_returns_escalate_action(self) -> None:
        resp = _response(escalate=True, reply="escalating")
        d = self._decide(resp)
        assert d.action == "escalate"
        assert d.reason == "response_escalate"

    def test_escalation_calls_transition_to_human_assigned(self) -> None:
        resp = _response(escalate=True)
        self._decide(resp)
        self._mock_transition.assert_called_once()
        _, kwargs = self._mock_transition.call_args
        assert kwargs["target"] == ConversationState.HUMAN_ASSIGNED

    def test_escalation_no_draft_message(self) -> None:
        d = self._decide(_response(escalate=True))
        assert d.draft_message_id is None

    # ---- Branch 2: Approval (requires_approval) -------------------------

    def test_approval_returns_approval_action(self) -> None:
        resp = _response(requires_approval=True, confidence=0.5)
        d = self._decide(resp)
        assert d.action == "approval"
        assert d.reason == "requires_approval"

    def test_approval_creates_draft_message(self) -> None:
        resp = _response(requires_approval=True, confidence=0.5)
        session = _fake_session()
        orch = _make_orchestrator(session)
        conv = _fake_conversation(ConversationState.AI_ACTIVE)
        contact = _fake_contact()
        draft = MagicMock()
        draft.id = uuid.uuid4()
        with patch.object(orch, "_create_draft_message", return_value=draft) as mock_draft:
            with patch.object(orch, "_transition"):
                d = orch._decide(conv, contact, resp)
        mock_draft.assert_called_once()
        _, kwargs = mock_draft.call_args
        assert kwargs["status"] == MessageDeliveryStatus.DRAFT
        assert d.draft_message_id == draft.id

    def test_approval_transitions_to_awaiting_approval(self) -> None:
        resp = _response(requires_approval=True)
        self._decide(resp)
        self._mock_transition.assert_called_once()
        _, kwargs = self._mock_transition.call_args
        assert kwargs["target"] == ConversationState.AWAITING_APPROVAL

    # ---- Branch 3: FAQ auto-send (confidence > 0.85) --------------------

    def test_faq_auto_send_above_threshold(self) -> None:
        resp = _response(confidence=CONFIDENCE_AUTO_REPLY_THRESHOLD + 0.01)
        d = self._decide(resp)
        assert d.action == "auto_send"
        assert d.reason == "faq_auto_send"

    def test_faq_auto_send_at_threshold_is_not_auto(self) -> None:
        # Exactly 0.85 — NOT auto-send (rule is strictly >).
        resp = _response(confidence=CONFIDENCE_AUTO_REPLY_THRESHOLD)
        d = self._decide(resp)
        assert d.action != "auto_send"

    def test_faq_auto_send_has_delay(self) -> None:
        resp = _response(confidence=0.95, reply="hello world")
        d = self._decide(resp)
        assert d.delay_seconds is not None
        assert d.delay_seconds > 0

    def test_faq_auto_send_uses_queued_status(self) -> None:
        resp = _response(confidence=0.95)
        session = _fake_session()
        orch = _make_orchestrator(session)
        conv = _fake_conversation(ConversationState.AI_ACTIVE)
        contact = _fake_contact()
        draft = MagicMock()
        draft.id = uuid.uuid4()
        with patch.object(orch, "_create_draft_message", return_value=draft) as mock_draft:
            with patch.object(orch, "_transition"):
                orch._decide(conv, contact, resp)
        mock_draft.assert_called_once()
        _, kwargs = mock_draft.call_args
        # auto-send drafts should default to QUEUED (the default in _create_draft_message)
        assert kwargs.get("status", MessageDeliveryStatus.QUEUED) == MessageDeliveryStatus.QUEUED

    def test_faq_auto_send_does_not_transition_state(self) -> None:
        resp = _response(confidence=0.95)
        self._decide(resp)
        # No state transition for auto-send — conversation stays AI_ACTIVE.
        self._mock_transition.assert_not_called()

    # ---- Branch 4: Low-confidence guard ---------------------------------

    def test_low_confidence_returns_approval(self) -> None:
        resp = _response(confidence=0.5, requires_approval=False)
        d = self._decide(resp)
        assert d.action == "approval"
        assert d.reason == "low_confidence"

    def test_low_confidence_transitions_to_awaiting_approval(self) -> None:
        resp = _response(confidence=0.5)
        self._decide(resp)
        self._mock_transition.assert_called_once()
        _, kwargs = self._mock_transition.call_args
        assert kwargs["target"] == ConversationState.AWAITING_APPROVAL

    def test_noop_when_no_reply(self) -> None:
        resp = _response(confidence=0.1, reply="", requires_approval=False, escalate=False)
        d = self._decide(resp)
        assert d.action == "noop"

    # ---- Categorization side-effects ------------------------------------

    def test_categorization_fires_on_every_branch(self) -> None:
        """Suggested tags produce TagSuggestions regardless of the primary action."""
        tags = ["Buyer", "Seller"]
        for resp in [
            _response(suggested_tags=tags, confidence=0.95),          # auto_send
            _response(suggested_tags=tags, requires_approval=True),   # approval
            _response(suggested_tags=tags, escalate=True),            # escalate
            _response(suggested_tags=tags, confidence=0.4),           # low_confidence
        ]:
            self._decide(resp)
            assert self._mock_suggest.call_count == len(tags), (
                f"Expected {len(tags)} suggestions for action {resp}"
            )
            # Reset for next iteration
            self._mock_suggest.reset_mock()

    def test_categorization_tag_ids_returned_in_decision(self) -> None:
        tag_id = uuid.uuid4()
        suggestion_mock = MagicMock(id=tag_id)
        resp = _response(confidence=0.95, suggested_tags=["Buyer"])
        session = _fake_session()
        orch = _make_orchestrator(session)
        conv = _fake_conversation(ConversationState.AI_ACTIVE)
        contact = _fake_contact()
        draft = MagicMock()
        draft.id = uuid.uuid4()
        with patch.object(orch, "_create_draft_message", return_value=draft):
            with patch.object(orch, "_transition"):
                with patch(
                    "app.modules.ai.service.CategorizationService.create_suggestion_sync",
                    return_value=suggestion_mock,
                ):
                    d = orch._decide(conv, contact, resp)
        assert tag_id in d.tag_suggestion_ids

    # ---- Escalation takes priority over requires_approval ---------------

    def test_escalation_wins_over_requires_approval(self) -> None:
        """escalate=True + requires_approval=True → escalate takes priority."""
        resp = _response(escalate=True, requires_approval=True)
        d = self._decide(resp)
        assert d.action == "escalate"

    def test_escalation_wins_over_high_confidence(self) -> None:
        """escalate=True + confidence=0.99 → escalate takes priority."""
        resp = _response(escalate=True, confidence=0.99)
        d = self._decide(resp)
        assert d.action == "escalate"

    # ---- send_contact_card flag ---------------------------------------

    def test_send_contact_card_on_decision(self) -> None:
        """send_contact_card=True is reflected in the Decision."""
        resp = _response(send_contact_card=True, confidence=0.95)
        d = self._decide(resp)
        assert d.send_contact_card is True

    def test_send_contact_card_passes_msg_type_to_draft(self) -> None:
        """send_contact_card=True → _create_draft_message receives msg_type='contact'."""
        resp = _response(send_contact_card=True, confidence=0.95)
        session = _fake_session()
        orch = _make_orchestrator(session)
        conv = _fake_conversation(ConversationState.AI_ACTIVE)
        contact = _fake_contact()
        draft = MagicMock()
        draft.id = uuid.uuid4()
        with patch.object(orch, "_create_draft_message", return_value=draft) as mock_draft:
            with patch.object(orch, "_transition"):
                orch._decide(conv, contact, resp)
        mock_draft.assert_called_once()
        _, kwargs = mock_draft.call_args
        assert kwargs["msg_type"] == "contact"

    def test_send_contact_card_approval_path(self) -> None:
        """send_contact_card on requires_approval branch — msg_type passed."""
        resp = _response(send_contact_card=True, requires_approval=True)
        session = _fake_session()
        orch = _make_orchestrator(session)
        conv = _fake_conversation(ConversationState.AI_ACTIVE)
        contact = _fake_contact()
        draft = MagicMock()
        draft.id = uuid.uuid4()
        with patch.object(orch, "_create_draft_message", return_value=draft) as mock_draft:
            with patch.object(orch, "_transition"):
                d = orch._decide(conv, contact, resp)
        assert d.send_contact_card is True
        mock_draft.assert_called_once()
        _, kwargs = mock_draft.call_args
        assert kwargs["msg_type"] == "contact"

    # ---- send_business_card_image flag --------------------------------

    def test_send_business_card_image_on_decision(self) -> None:
        """send_business_card_image=True is reflected in the Decision."""
        resp = _response(send_business_card_image=True, confidence=0.95)
        d = self._decide(resp)
        assert d.send_business_card_image is True

    def test_send_business_card_image_reads_setting(self) -> None:
        """send_business_card_image=True calls _get_business_card_media_id."""
        resp = _response(send_business_card_image=True, confidence=0.95)
        session = _fake_session()
        orch = _make_orchestrator(session)
        conv = _fake_conversation(ConversationState.AI_ACTIVE)
        contact = _fake_contact()
        draft = MagicMock()
        draft.id = uuid.uuid4()
        with patch.object(orch, "_get_business_card_media_id", return_value=None) as mock_get:
            with patch.object(orch, "_create_draft_message", return_value=draft):
                with patch.object(orch, "_transition"):
                    orch._decide(conv, contact, resp)
        mock_get.assert_called_once()


# ---------------------------------------------------------------------------
# _create_draft_message — new params
# ---------------------------------------------------------------------------

class TestCreateDraftMessage:
    def test_msg_type_contact_formats_content(self) -> None:
        """msg_type='contact' overrides content to the persona's formatted name+phone."""
        session = _fake_session()
        orch = _make_orchestrator(session)
        msg = orch._create_draft_message(
            conversation_id=uuid.uuid4(),
            content="some ai reply",
            msg_type="contact",
        )
        assert msg.content == "Sara Ahmed — +971 50 000 0000"
        assert msg.msg_type == "contact"

    def test_msg_type_contact_default(self) -> None:
        """Without msg_type, no override occurs."""
        session = _fake_session()
        orch = _make_orchestrator(session)
        msg = orch._create_draft_message(
            conversation_id=uuid.uuid4(),
            content="plain text",
        )
        assert msg.content == "plain text"
        assert msg.msg_type is None

    def test_media_asset_id_links_to_message(self) -> None:
        """media_asset_id is looked up and linked to the draft."""
        from app.modules.media.models import MediaAsset

        asset_id = uuid.uuid4()
        asset = MagicMock(spec=MediaAsset)
        asset.message_id = None
        asset.file_data = b"fake-jpeg-bytes"  # must be truthy for validation
        session = _fake_session()
        session.get = MagicMock(return_value=asset)
        orch = _make_orchestrator(session)
        msg = orch._create_draft_message(
            conversation_id=uuid.uuid4(),
            content="sure here is my card",
            media_asset_id=asset_id,
        )
        session.get.assert_called_once()
        assert session.get.call_args[0][0] is MediaAsset
        assert session.get.call_args[0][1] == asset_id
        assert asset.message_id == msg.id

    def test_media_asset_id_missing_logs_warning(self) -> None:
        """A missing media_asset_id logs but does not crash."""
        session = _fake_session()
        session.get = MagicMock(return_value=None)
        orch = _make_orchestrator(session)
        msg = orch._create_draft_message(
            conversation_id=uuid.uuid4(),
            content="here is my card",
            media_asset_id=uuid.uuid4(),
        )
        assert msg is not None

    def test_both_contact_and_media(self) -> None:
        """send_contact_card + send_business_card_image together — contact type
        + media linked."""
        from app.modules.media.models import MediaAsset

        asset_id = uuid.uuid4()
        asset = MagicMock(spec=MediaAsset)
        asset.message_id = None
        asset.file_data = b"fake-jpeg-bytes"
        session = _fake_session()
        session.get = MagicMock(return_value=asset)
        orch = _make_orchestrator(session)
        msg = orch._create_draft_message(
            conversation_id=uuid.uuid4(),
            content="here is my contact and card",
            msg_type="contact",
            media_asset_id=asset_id,
        )
        assert msg.content == "Sara Ahmed — +971 50 000 0000"
        assert msg.msg_type == "contact"
        assert asset.message_id == msg.id
