"""Unit tests for market module repository utility methods."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.market.models import MarketMessage, Product
from app.modules.market.repository import (
    MarketMessageRepository,
    ProductAliasRepository,
    ProductRepository,
)


@pytest.mark.asyncio
async def test_market_message_repo_model():
    """Repository is properly configured with the correct model."""
    session = AsyncMock()
    repo = MarketMessageRepository(session)
    assert repo.model is MarketMessage


@pytest.mark.asyncio
async def test_product_repo_model():
    session = AsyncMock()
    repo = ProductRepository(session)
    assert repo.model is Product


class TestProductAliasRepository:
    def test_resolve_empty(self):
        session = AsyncMock()
        repo = ProductAliasRepository(session)
        assert repo.session is session
