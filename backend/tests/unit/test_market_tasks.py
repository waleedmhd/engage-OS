"""Unit tests for market module Celery tasks."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.modules.market.tasks import classify_message_task, expire_market_messages_task


def test_classify_message_task_invalid_uuid():
    result = classify_message_task("not-a-uuid")
    assert result == {"action": "noop", "reason": "invalid_message_id"}


def test_classify_message_task_valid_uuid():
    mid = str(uuid.uuid4())
    with patch(
        "app.modules.market.tasks.sync_session_factory"
    ) as mock_factory, patch(
        "app.modules.market.tasks.MarketClassificationService.classify_with_llm_sync"
    ) as mock_classify:
        mock_session = MagicMock()
        mock_factory.return_value = mock_session

        result = classify_message_task(mid)

        assert result["action"] == "classified"
        assert result["message_id"] == mid
        mock_factory.assert_called_once()
        mock_classify.assert_called_once_with(mock_session.__enter__.return_value, uuid.UUID(mid))
        mock_session.__enter__().commit.assert_called_once()


# ---------------------------------------------------------------- expiry sweep


def test_expire_task_returns_combined_counts():
    """Sweep task unpacks both expired and unreviewed_expired counts."""
    with patch(
        "app.modules.market.tasks.sync_session_factory"
    ) as mock_factory:
        mock_session = MagicMock()
        mock_factory.return_value = mock_session

        with patch(
            "app.modules.market.repository.MarketMessageRepository"
        ) as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.expire_stale_sync.return_value = {
                "expired": 5,
                "unreviewed_expired": 2,
            }
            mock_repo_cls.return_value = mock_repo

            result = expire_market_messages_task()

    assert result["action"] == "expired"
    assert result["expired"] == 5
    assert result["unreviewed_expired"] == 2
    assert result["count"] == 7


def test_expire_task_handles_zero_unreviewed():
    """When no PENDING items are stale, unreviewed_expired is zero."""
    with patch(
        "app.modules.market.tasks.sync_session_factory"
    ) as mock_factory:
        mock_session = MagicMock()
        mock_factory.return_value = mock_session

        with patch(
            "app.modules.market.repository.MarketMessageRepository"
        ) as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.expire_stale_sync.return_value = {
                "expired": 3,
                "unreviewed_expired": 0,
            }
            mock_repo_cls.return_value = mock_repo

            result = expire_market_messages_task()

    assert result["expired"] == 3
    assert result["unreviewed_expired"] == 0
    assert result["count"] == 3
