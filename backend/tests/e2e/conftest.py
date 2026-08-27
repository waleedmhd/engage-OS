"""E2E-tier conftest. Auto-marks every test under tests/e2e/ as `e2e`."""
from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "tests/e2e/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)


@pytest.fixture
def full_stack(pg_session, redis_client, celery_eager, respx_mock):
    """Convenience composite fixture for E2E tests."""
    return {
        "db": pg_session,
        "redis": redis_client,
        "celery": celery_eager,
        "respx": respx_mock,
    }
