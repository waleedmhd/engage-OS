"""Unit tests for the sync settings read helpers used by the AI orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.modules.settings.repository import get_bool_setting_sync, get_test_numbers_sync


def _session_returning(row):
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session.execute.return_value = result
    return session


def test_returns_default_when_row_missing():
    session = _session_returning(None)
    assert get_bool_setting_sync(session, "ai.kill_switch", default=False) is False
    assert get_bool_setting_sync(session, "ai.auto_send_enabled", default=True) is True


def test_returns_stored_value():
    row = MagicMock()
    row.value = {"enabled": True}
    session = _session_returning(row)
    assert get_bool_setting_sync(session, "ai.kill_switch", default=False) is True


def test_malformed_value_falls_back_to_default():
    row = MagicMock()
    row.value = {}
    session = _session_returning(row)
    assert get_bool_setting_sync(session, "ai.kill_switch", default=False) is False


def test_get_test_numbers_returns_empty_when_row_missing():
    session = _session_returning(None)
    assert get_test_numbers_sync(session) == []


def test_get_test_numbers_returns_list():
    row = MagicMock()
    row.value = {"numbers": ["+123", "+456"]}
    session = _session_returning(row)
    assert get_test_numbers_sync(session) == ["+123", "+456"]


def test_get_test_numbers_malformed_value_falls_back():
    row = MagicMock()
    row.value = {"numbers": "not-a-list"}
    session = _session_returning(row)
    assert get_test_numbers_sync(session) == []
