"""Queue / Celery routing tests.

Asserts:
  * Every TASK_ROUTES glob matches a registered task name.
  * Worker config: task_acks_late=True, worker_prefetch_multiplier=1.
  * Beat schedule entries match the expected task names.
  * `request_ai_reply_task` has correct retry policy (max_retries, bind, acks_late).
"""
from __future__ import annotations

import fnmatch

import pytest

from app.workers.beat_schedule import BEAT_SCHEDULE
from app.workers.queues import ALL_QUEUES, TASK_ROUTES


@pytest.fixture(scope="module")
def celery_app_obj():
    # Importing app.workers.celery_app (or app.celery_app — the codebase uses both)
    # loads & registers all task modules via autodiscovery.
    try:
        from app.workers import celery_app as mod  # type: ignore[attr-defined]
        app_obj = getattr(mod, "celery_app", None) or mod.app
    except ImportError:
        from app import celery_app as mod
        app_obj = getattr(mod, "celery_app", None) or mod.app
    # autodiscover_tasks is lazy — task modules are only imported on worker
    # boot or first send. Force the import so the registry is populated.
    app_obj.loader.import_default_modules()
    return app_obj


def test_known_queues_match_task_routes(celery_app_obj):
    for pattern, route in TASK_ROUTES.items():
        assert route["queue"] in ALL_QUEUES, (
            f"TASK_ROUTES route {pattern!r} → unknown queue {route['queue']!r}"
        )


def test_every_route_glob_matches_a_registered_task(celery_app_obj):
    """Catch typos: a TASK_ROUTES entry for a non-existent module silently routes nothing."""
    registered = set(celery_app_obj.tasks.keys())
    misses: list[str] = []
    for pattern in TASK_ROUTES.keys():
        if not any(fnmatch.fnmatch(name, pattern) for name in registered):
            misses.append(pattern)
    assert not misses, f"TASK_ROUTES patterns match no registered tasks: {misses}"


def test_worker_config_acks_late_and_prefetch_one(celery_app_obj):
    conf = celery_app_obj.conf
    assert conf.task_acks_late is True, (
        "acks_late must be True so a worker crash re-queues the task. "
        "With False, in-flight tasks are lost on worker SIGKILL."
    )
    assert conf.worker_prefetch_multiplier == 1, (
        "prefetch_multiplier must be 1 so a slow task doesn't starve siblings."
    )


def test_beat_schedule_task_names_resolve(celery_app_obj):
    registered = set(celery_app_obj.tasks.keys())
    missing = [
        f"{name} → {entry['task']}"
        for name, entry in BEAT_SCHEDULE.items()
        if entry["task"] not in registered
    ]
    assert not missing, f"Beat schedule references unregistered task(s): {missing}"


def test_ai_request_task_has_retry_policy(celery_app_obj):
    task = celery_app_obj.tasks.get("ai.tasks.request_ai_reply_task")
    assert task is not None, "ai.tasks.request_ai_reply_task missing — autodiscovery broken"
    assert task.max_retries is not None and task.max_retries >= 3
    assert task.acks_late is True


def test_send_ai_reply_task_registered(celery_app_obj):
    assert "ai.tasks.send_ai_reply_task" in celery_app_obj.tasks
