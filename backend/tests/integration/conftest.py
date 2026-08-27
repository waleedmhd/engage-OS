"""Integration-tier conftest.

Every test under tests/integration/ is auto-marked `integration` so a single
`-m integration` selector picks them up. The shared `pg_session` and
`redis_client` fixtures already skip if infra is missing.
"""
from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "tests/integration/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.integration)
