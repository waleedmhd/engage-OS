"""Live-tier conftest.

Auto-marks every test under tests/live/ as `live` and enforces
RUN_LIVE_TESTS=1 + presence of real Meta/Anthropic credentials. Live tests are
EXCLUDED by default (see pyproject.toml addopts: `-m 'not live'`).
"""
from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "tests/live/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.live)


@pytest.fixture(autouse=True)
def _require_live_env():
    if os.environ.get("RUN_LIVE_TESTS") != "1":
        pytest.skip(
            "Live tests require RUN_LIVE_TESTS=1 (real Meta/Anthropic calls; costs money; sends WhatsApp messages)."
        )
    for key in ("META_ACCESS_TOKEN", "META_PHONE_NUMBER_ID", "ANTHROPIC_API_KEY"):
        val = os.environ.get(key) or ""
        if not val or val.startswith("test-"):
            pytest.skip(f"Live test requires real {key} in environment (.env)")
