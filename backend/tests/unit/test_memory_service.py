"""Unit tests for contacts/memory_service.py — file I/O, formatting, DB tracking,
and the _call_haiku_for_summary async retry logic.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.modules.contacts.constants import ContactStatus
from app.modules.contacts.memory_models import ClientMemory
from app.modules.contacts.memory_service import (
    _call_haiku_for_summary,
    _ensure_memories_dir,
    _read_memory_file,
    _strip_markdown_fence,
    _upsert_tracking_row,
    _write_memory_file,
    get_memory_text,
    load_memory,
    update_memory_from_history_sync,
    update_memory_sync,
)
from app.modules.contacts.models import Contact


def _create_contact(session, *, phone: str) -> Contact:
    """Create a minimal Contact row for FK referential integrity."""
    c = Contact(phone=phone, status=ContactStatus.ACTIVE.value)
    session.add(c)
    session.flush()
    return c


@pytest.fixture
def contact_id(tmp_path_factory):
    return uuid.uuid4()


_phone_counter = 0


@pytest.fixture
def contact_for_db(pg_session):
    """Create a real Contact row so FK constraints on client_memories pass."""
    global _phone_counter
    _phone_counter += 1
    return _create_contact(pg_session, phone=f"+1555mem{_phone_counter:04d}")


@pytest.fixture
def temp_media_root(tmp_path):
    """Patch _media_root to return a temp dir so we don't touch real disk."""
    mem_dir = tmp_path / "media"
    (mem_dir / "memories").mkdir(parents=True)
    with patch(
        "app.modules.contacts.memory_service._media_root", return_value=mem_dir
    ):
        yield mem_dir


# ------------------------------------------------------------------- get_memory_text


class TestGetMemoryText:
    def test_returns_none_when_no_file(self, contact_id, temp_media_root):
        assert get_memory_text(contact_id) is None

    def test_full_memory_with_all_sections(self, contact_id, temp_media_root):
        data = {
            "summary": "Customer buys iPhones from HK spec.",
            "key_points": ["Prefers HK spec", "Buys in bulk", "Pays via wire"],
            "preferences": {"language": "English", "contact_time": "morning"},
        }
        _write_memory_file(contact_id, data)

        text = get_memory_text(contact_id)
        assert text is not None
        assert "Customer buys iPhones from HK spec." in text
        assert "Prefers HK spec" in text
        assert "Buys in bulk" in text
        assert "language: English" in text
        assert "contact_time: morning" in text
        assert "Key points:" in text
        assert "Known preferences:" in text

    def test_summary_only_no_key_points_or_prefs(self, contact_id, temp_media_root):
        data = {"summary": "Just a summary.", "key_points": [], "preferences": {}}
        _write_memory_file(contact_id, data)

        text = get_memory_text(contact_id)
        assert text is not None
        assert "Just a summary." in text
        assert "Key points:" not in text
        assert "Known preferences:" not in text

    def test_empty_summary_returns_none(self, contact_id, temp_media_root):
        data = {"summary": "", "key_points": [], "preferences": {}}
        _write_memory_file(contact_id, data)

        assert get_memory_text(contact_id) is None

    def test_only_key_points_no_summary(self, contact_id, temp_media_root):
        data = {
            "summary": "  ",
            "key_points": ["Bullet A", "Bullet B"],
            "preferences": {},
        }
        _write_memory_file(contact_id, data)

        text = get_memory_text(contact_id)
        assert text is not None
        assert "Bullet A" in text
        assert "Key points:" in text

    def test_goals_rendered_with_status_labels(self, contact_id, temp_media_root):
        data = {
            "summary": "Customer summary.",
            "key_points": [],
            "preferences": {},
            "goals": [
                {"field": "name", "value": "Ahmed", "status": "confirmed"},
                {"field": "company", "value": "Dubai Trading", "status": "confirmed"},
                {"field": "product_interest", "value": "iPhone 15", "status": "tentative"},
                {"field": "buy_sell", "value": "both?", "status": "needs_clarification"},
            ],
        }
        _write_memory_file(contact_id, data)

        text = get_memory_text(contact_id)
        assert text is not None
        assert "Learned about this contact:" in text
        # confirmed facts — no status label
        assert "name: Ahmed" in text
        assert "company: Dubai Trading" in text
        assert "(confirmed)" not in text
        # tentative
        assert "product_interest: iPhone 15 (tentative)" in text
        # needs clarification
        assert "buy_sell: both? (needs clarification)" in text

    def test_goals_only_no_summary(self, contact_id, temp_media_root):
        data = {
            "summary": "",
            "key_points": [],
            "preferences": {},
            "goals": [
                {"field": "name", "value": "Sara", "status": "confirmed"},
            ],
        }
        _write_memory_file(contact_id, data)

        text = get_memory_text(contact_id)
        assert text is not None
        assert "Learned about this contact:" in text
        assert "name: Sara" in text
        assert "Client memory" not in text  # no summary section


# ------------------------------------------------------------------- load_memory


class TestLoadMemory:
    def test_returns_none_when_no_file(self, contact_id, temp_media_root):
        assert load_memory(contact_id) is None

    def test_returns_dict_when_file_exists(self, contact_id, temp_media_root):
        data = {"summary": "Test", "version": 3}
        _write_memory_file(contact_id, data)

        loaded = load_memory(contact_id)
        assert loaded is not None
        assert loaded["summary"] == "Test"
        assert loaded["version"] == 3


# ------------------------------------------------------------------- _read_memory_file


class TestReadMemoryFile:
    def test_nonexistent_file(self, contact_id, temp_media_root):
        assert _read_memory_file(contact_id) is None

    def test_valid_json(self, contact_id, temp_media_root):
        data = {"summary": "Valid", "key_points": ["A"]}
        _write_memory_file(contact_id, data)

        result = _read_memory_file(contact_id)
        assert result is not None
        assert result["summary"] == "Valid"
        assert result["key_points"] == ["A"]

    def test_corrupted_json_returns_none(self, contact_id, temp_media_root):
        from app.modules.contacts.memory_service import _memory_file_path

        _ensure_memories_dir()
        path = _memory_file_path(contact_id)
        path.write_text("not valid json {{{", encoding="utf-8")

        assert _read_memory_file(contact_id) is None


# ---------------------------------------------------------------- _write_memory_file


class TestWriteMemoryFile:
    def test_creates_dir_and_writes(self, contact_id, temp_media_root):
        from app.modules.contacts.memory_service import _memory_file_path

        data = {"summary": "Written", "version": 1}
        _write_memory_file(contact_id, data)

        path = _memory_file_path(contact_id)
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["summary"] == "Written"
        assert loaded["version"] == 1

    def test_overwrites_existing(self, contact_id, temp_media_root):
        _write_memory_file(contact_id, {"version": 1})
        _write_memory_file(contact_id, {"version": 2})
        loaded = _read_memory_file(contact_id)
        assert loaded is not None
        assert loaded["version"] == 2


# --------------------------------------------------------------- _upsert_tracking_row


class TestUpsertTrackingRow:
    def test_insert_new_row(self, pg_session, contact_for_db, temp_media_root):
        data = {
            "summary": "iPhone buyer based in Dubai.",
            "version": 1,
            "total_interactions": 1,
        }
        _upsert_tracking_row(pg_session, contact_for_db.id, data)
        pg_session.flush()

        row = pg_session.execute(
            select(ClientMemory).where(ClientMemory.contact_id == contact_for_db.id)
        ).scalar_one_or_none()
        assert row is not None
        assert row.version == 1
        assert row.total_interactions == 1
        assert row.summary_preview == "iPhone buyer based in Dubai."
        assert "memories" in row.file_path

    def test_update_existing_row(self, pg_session, contact_for_db, temp_media_root):
        data_v1 = {
            "summary": "Version one.",
            "version": 1,
            "total_interactions": 1,
        }
        _upsert_tracking_row(pg_session, contact_for_db.id, data_v1)
        pg_session.flush()

        data_v2 = {
            "summary": "Version two updated.",
            "version": 2,
            "total_interactions": 2,
        }
        _upsert_tracking_row(pg_session, contact_for_db.id, data_v2)
        pg_session.flush()

        rows = pg_session.execute(
            select(ClientMemory).where(ClientMemory.contact_id == contact_for_db.id)
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].version == 2
        assert rows[0].total_interactions == 2
        assert rows[0].summary_preview == "Version two updated."

    def test_long_summary_truncated_to_500(self, pg_session, contact_for_db, temp_media_root):
        long_summary = "X" * 600
        data = {
            "summary": long_summary,
            "version": 1,
            "total_interactions": 1,
        }
        _upsert_tracking_row(pg_session, contact_for_db.id, data)
        pg_session.flush()

        row = pg_session.execute(
            select(ClientMemory).where(ClientMemory.contact_id == contact_for_db.id)
        ).scalar_one_or_none()
        assert row is not None
        assert len(row.summary_preview) == 500

    def test_empty_summary_stores_none_preview(self, pg_session, contact_for_db, temp_media_root):
        data = {"summary": "", "version": 1, "total_interactions": 1}
        _upsert_tracking_row(pg_session, contact_for_db.id, data)
        pg_session.flush()

        row = pg_session.execute(
            select(ClientMemory).where(ClientMemory.contact_id == contact_for_db.id)
        ).scalar_one_or_none()
        assert row is not None
        assert row.summary_preview is None


# ------------------------------------------------------------- update_memory_sync


class TestUpdateMemorySync:
    def test_creates_new_memory(self, pg_session, contact_for_db, temp_media_root):
        """update_memory_sync with no existing file should create one."""
        fake_summary = {
            "summary": "New customer — Samsung buyer.",
            "key_points": ["Buys Samsung", "Based in UAE"],
            "preferences": {"language": "English"},
            "goals": [
                {"field": "product_interest", "value": "Samsung phones", "status": "confirmed"},
                {"field": "buy_sell", "value": "buyer", "status": "tentative"},
            ],
        }
        with patch(
            "app.modules.contacts.memory_service.asyncio.run",
            return_value=fake_summary,
        ):
            update_memory_sync(
                pg_session,
                contact_for_db.id,
                messages=[{"role": "user", "content": "Hi I buy Samsung"}],
                ai_reply="What Samsung models do you buy?",
            )

        pg_session.flush()

        loaded = load_memory(contact_for_db.id)
        assert loaded is not None
        assert loaded["summary"] == "New customer — Samsung buyer."
        assert loaded["version"] == 1
        assert loaded["total_interactions"] == 1

        row = pg_session.execute(
            select(ClientMemory).where(ClientMemory.contact_id == contact_for_db.id)
        ).scalar_one_or_none()
        assert row is not None
        assert row.version == 1
        assert row.summary_preview == "New customer — Samsung buyer."

    def test_updates_existing_memory(self, pg_session, contact_for_db, temp_media_root):
        """Updating an existing memory should increment version."""
        existing = {
            "contact_id": str(contact_for_db.id),
            "summary": "Existing summary.",
            "key_points": ["Old point"],
            "preferences": {},
            "version": 3,
            "total_interactions": 10,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        _write_memory_file(contact_for_db.id, existing)

        updated_summary = {
            "summary": "Updated summary with more context.",
            "key_points": ["Old point", "New point"],
            "preferences": {"language": "Urdu"},
            "goals": [
                {"field": "name", "value": "Ali", "status": "confirmed"},
            ],
        }
        with patch(
            "app.modules.contacts.memory_service.asyncio.run",
            return_value=updated_summary,
        ):
            update_memory_sync(
                pg_session,
                contact_for_db.id,
                messages=[{"role": "user", "content": "I also want Google Pixel"}],
                ai_reply="Do you want new or used Pixel?",
            )

        pg_session.flush()

        loaded = load_memory(contact_for_db.id)
        assert loaded is not None
        assert loaded["version"] == 4
        assert loaded["total_interactions"] == 11
        assert loaded["summary"] == "Updated summary with more context."

    def test_summarise_failure_preserves_existing(self, pg_session, contact_for_db, temp_media_root):
        """When summarise returns None, existing memory is NOT corrupted."""
        existing = {
            "contact_id": str(contact_for_db.id),
            "summary": "Safe summary.",
            "version": 1,
            "total_interactions": 1,
        }
        _write_memory_file(contact_for_db.id, existing)

        with patch(
            "app.modules.contacts.memory_service.asyncio.run",
            return_value=None,
        ):
            update_memory_sync(
                pg_session,
                contact_for_db.id,
                messages=[{"role": "user", "content": "Hello"}],
                ai_reply="Hi!",
            )

        loaded = load_memory(contact_for_db.id)
        assert loaded is not None
        assert loaded["version"] == 1
        assert loaded["summary"] == "Safe summary."


# ---------------------------------------------------------------- _strip_markdown_fence


class TestStripMarkdownFence:
    def test_no_fence_passthrough(self):
        text = '{"summary": "hello"}'
        assert _strip_markdown_fence(text) == text

    def test_strips_fence_with_language_tag(self):
        text = '```json\n{"summary": "hello"}\n```'
        assert _strip_markdown_fence(text) == '{"summary": "hello"}'

    def test_strips_fence_without_language_tag(self):
        text = '```\n{"summary": "hello"}\n```'
        assert _strip_markdown_fence(text) == '{"summary": "hello"}'

    def test_leading_fence_only(self):
        text = '```json\n{"summary": "hello"}'
        assert _strip_markdown_fence(text) == '{"summary": "hello"}'

    def test_trailing_fence_only(self):
        text = '{"summary": "hello"}\n```'
        assert _strip_markdown_fence(text) == '{"summary": "hello"}'

    def test_already_clean_json(self):
        text = '  \n{"summary": "hello"}\n  '
        assert _strip_markdown_fence(text) == '{"summary": "hello"}'


# -------------------------------------------------------------- _call_haiku_for_summary


def _mock_response(text: str, type_: str = "text") -> MagicMock:
    """Build a mock Anthropic response whose .content is iterable blocks."""
    block = MagicMock()
    block.text = text
    block.type = type_
    response = MagicMock()
    response.content = [block]
    return response


@pytest.fixture
def memory_settings() -> Settings:
    return Settings(ANTHROPIC_API_KEY="test-key")


class TestCallHaikuForSummary:
    """Cover the retry paths in _call_haiku_for_summary (async, with mocked client)."""

    @pytest.mark.asyncio
    async def test_success_first_attempt(self, memory_settings):
        mock = AsyncMock()
        mock.messages.create.return_value = _mock_response(
            json.dumps({"summary": "Success", "key_points": [], "preferences": {}, "goals": []})
        )
        mock.close = AsyncMock()
        with patch(
            "app.modules.contacts.memory_service.AsyncAnthropic",
            return_value=mock,
        ):
            result = await _call_haiku_for_summary("test message", memory_settings)
        assert result is not None
        assert result["summary"] == "Success"
        assert mock.messages.create.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_api_error_then_success(self, memory_settings):
        mock = AsyncMock()
        mock.messages.create = AsyncMock(
            side_effect=[Exception("API down"), _mock_response(
                json.dumps({"summary": "Retry win", "key_points": [], "preferences": {}, "goals": []})
            )]
        )
        mock.close = AsyncMock()
        with patch(
            "app.modules.contacts.memory_service.AsyncAnthropic",
            return_value=mock,
        ):
            result = await _call_haiku_for_summary("test message", memory_settings)
        assert result is not None
        assert result["summary"] == "Retry win"
        assert mock.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_success_with_markdown_fence_first_attempt(self, memory_settings):
        """Haiku wraps JSON in ```json ... ``` — strip and parse."""
        raw = '```json\n{"summary": "Fenced", "key_points": [], "preferences": {}, "goals": []}\n```'
        mock = AsyncMock()
        mock.messages.create.return_value = _mock_response(raw)
        mock.close = AsyncMock()
        with patch(
            "app.modules.contacts.memory_service.AsyncAnthropic",
            return_value=mock,
        ):
            result = await _call_haiku_for_summary("test message", memory_settings)
        assert result is not None
        assert result["summary"] == "Fenced"
        assert mock.messages.create.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_bad_json_then_success(self, memory_settings):
        mock = AsyncMock()
        mock.messages.create = AsyncMock(
            side_effect=[
                _mock_response("not valid json {{{"),
                _mock_response(
                    json.dumps({"summary": "JSON retry win", "key_points": [], "preferences": {}, "goals": []})
                ),
            ]
        )
        mock.close = AsyncMock()
        with patch(
            "app.modules.contacts.memory_service.AsyncAnthropic",
            return_value=mock,
        ):
            result = await _call_haiku_for_summary("test message", memory_settings)
        assert result is not None
        assert result["summary"] == "JSON retry win"
        assert mock.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_both_attempts_fail_api_error(self, memory_settings):
        mock = AsyncMock()
        mock.messages.create = AsyncMock(side_effect=[Exception("down"), Exception("down again")])
        mock.close = AsyncMock()
        with patch(
            "app.modules.contacts.memory_service.AsyncAnthropic",
            return_value=mock,
        ):
            result = await _call_haiku_for_summary("test message", memory_settings)
        assert result is None
        assert mock.messages.create.call_count == 2

    @pytest.mark.asyncio
    async def test_both_attempts_bad_json(self, memory_settings):
        mock = AsyncMock()
        mock.messages.create = AsyncMock(
            side_effect=[
                _mock_response("still not json {{{"),
                _mock_response("also not json }}}"),
            ]
        )
        mock.close = AsyncMock()
        with patch(
            "app.modules.contacts.memory_service.AsyncAnthropic",
            return_value=mock,
        ):
            result = await _call_haiku_for_summary("test message", memory_settings)
        assert result is None
        assert mock.messages.create.call_count == 2


# -------------------------------------------------------------- update_memory_from_history_sync


class TestUpdateMemoryFromHistorySync:
    def test_creates_new_memory(self, pg_session, contact_for_db, temp_media_root):
        """When no memory file exists, a new one is created from history."""
        summary = {
            "summary": "New memory from history.",
            "key_points": ["Point 1"],
            "preferences": {},
            "goals": [],
        }
        with patch(
            "app.modules.contacts.memory_service.asyncio.run",
            return_value=summary,
        ):
            update_memory_from_history_sync(
                pg_session,
                contact_for_db.id,
                messages=[{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}],
            )

        pg_session.flush()

        loaded = load_memory(contact_for_db.id)
        assert loaded is not None
        assert loaded["version"] == 1
        assert loaded["total_interactions"] == 1
        assert loaded["summary"] == "New memory from history."

    def test_updates_existing_memory(self, pg_session, contact_for_db, temp_media_root):
        """When a memory file exists, it is updated with new context."""
        existing = {
            "contact_id": str(contact_for_db.id),
            "summary": "Old summary.",
            "key_points": ["Old point"],
            "preferences": {},
            "version": 2,
            "total_interactions": 5,
        }
        _write_memory_file(contact_for_db.id, existing)

        updated = {
            "summary": "Updated summary with old + new.",
            "key_points": ["Old point", "New point"],
            "preferences": {"language": "English"},
            "goals": [{"field": "name", "value": "Ahmed", "status": "confirmed"}],
        }
        with patch(
            "app.modules.contacts.memory_service.asyncio.run",
            return_value=updated,
        ):
            update_memory_from_history_sync(
                pg_session,
                contact_for_db.id,
                messages=[{"role": "user", "content": "My name is Ahmed"}],
            )

        pg_session.flush()

        loaded = load_memory(contact_for_db.id)
        assert loaded is not None
        assert loaded["version"] == 3
        assert loaded["total_interactions"] == 6
        assert loaded["summary"] == "Updated summary with old + new."

    def test_summarise_failure_preserves_existing(self, pg_session, contact_for_db, temp_media_root):
        """When Haiku summarisation fails, existing memory is not corrupted."""
        existing = {
            "contact_id": str(contact_for_db.id),
            "summary": "Safe summary.",
            "version": 1,
            "total_interactions": 1,
        }
        _write_memory_file(contact_for_db.id, existing)

        with patch(
            "app.modules.contacts.memory_service.asyncio.run",
            return_value=None,
        ):
            update_memory_from_history_sync(
                pg_session,
                contact_for_db.id,
                messages=[{"role": "user", "content": "Hello"}],
            )

        loaded = load_memory(contact_for_db.id)
        assert loaded is not None
        assert loaded["version"] == 1
        assert loaded["summary"] == "Safe summary."

    def test_creates_memory_when_none_exists(self, pg_session, contact_for_db, temp_media_root):
        """Creating memory from history when no file has ever existed works."""
        loaded_before = load_memory(contact_for_db.id)
        assert loaded_before is None

        summary = {
            "summary": "First ever memory.",
            "key_points": ["First contact"],
            "preferences": {},
            "goals": [],
        }
        with patch(
            "app.modules.contacts.memory_service.asyncio.run",
            return_value=summary,
        ):
            update_memory_from_history_sync(
                pg_session,
                contact_for_db.id,
                messages=[{"role": "user", "content": "Hi, first time chatting"}],
            )

        pg_session.flush()

        loaded = load_memory(contact_for_db.id)
        assert loaded is not None
        assert loaded["version"] == 1
        assert loaded["summary"] == "First ever memory."
