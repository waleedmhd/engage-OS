"""Celery application instance.

Worker (`-A app.celery_app.celery_app worker`) and beat (`... beat`) processes
load this module. Tasks are autodiscovered from every module's `tasks.py`.
"""

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.workers.beat_schedule import BEAT_SCHEDULE
from app.workers.queues import TASK_ROUTES

_settings = get_settings()
configure_logging(_settings)

celery_app = Celery(
    "engageos",
    broker=_settings.CELERY_BROKER_URL,
    backend=_settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes=TASK_ROUTES,
    beat_schedule=BEAT_SCHEDULE,
    timezone="UTC",
    enable_utc=True,
)

# --------------------------------------------------------------------------- #
# Post-fork cleanup (Msg-I9 fix)                                              #
# --------------------------------------------------------------------------- #
# Celery forks worker processes after the parent has potentially created a
# sync Redis client (via get_sync_redis()). The forked child inherits the
# parent's file-descriptor table, meaning both processes share the same
# underlying socket — concurrent reads/writes produce protocol framing errors.
#
# Clearing the lru_cache immediately after fork forces each child process to
# create its own Redis client with its own connection pool.
from celery.signals import worker_process_init  # noqa: E402


@worker_process_init.connect
def _reset_sync_redis_after_fork(**kwargs: object) -> None:
    """Clear the cached sync Redis client so each worker gets its own pool."""
    from app.core.redis import get_sync_redis  # local import: module may not be loaded yet

    get_sync_redis.cache_clear()


# Register all SQLAlchemy models before task discovery.
#
# Why this must happen here, before autodiscover_tasks():
#   autodiscover_tasks() imports every tasks.py at module level. Several of
#   those files pull in services/repositories that import ORM models (e.g.
#   ai.tasks → ai.service → categorization.service → categorization.models),
#   registering some mappers — but NOT auth.models, because auth tasks use a
#   local import inside the function body. When the first DB query runs in any
#   task, SQLAlchemy tries to configure ALL registered mappers at once.
#   ContactTag.approver (and other relationships) reference "User" via string
#   lookup. If User is not yet in the mapper registry, SQLAlchemy raises:
#     InvalidRequestError: expression 'User' failed to locate a name ('User')
#
#   Calling import_all_models() here guarantees every mapper is in the registry
#   before autodiscover_tasks() loads partial subsets of them.
from app.db.base import import_all_models  # noqa: E402

import_all_models()

# Task discovery — auto-discover every module's `tasks` submodule by scanning
# ``app/modules/`` for directories containing a ``tasks.py`` file.
# Previously hardcoded (22 explicit entries); auto-discovered as of 2026-07-22.
# Restore the explicit list if auto-discovery ever breaks.
import os as _os  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_modules_dir = _Path(__file__).resolve().parent / "modules"
_task_modules = sorted(
    f"app.modules.{entry}"
    for entry in _os.listdir(_modules_dir)
    if (_modules_dir / entry).is_dir()
    and not entry.startswith("_")
    and not entry.startswith(".")
    and (_modules_dir / entry / "tasks.py").is_file()
)
celery_app.autodiscover_tasks(_task_modules, related_name="tasks")
