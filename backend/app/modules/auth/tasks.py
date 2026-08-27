"""Auth Celery tasks.

Fix applied:
  Auth-I4 — prune_expired_refresh_tokens used asyncio.run() to drive an
             async SQLAlchemy session from inside a Celery task. This raises
             RuntimeError under Celery's gevent, eventlet, and asyncio
             concurrency pools because those pools run their own event loop
             — asyncio.run() cannot nest a new loop on top of a running one.

             Fix: rewritten using sync_session_factory() and a plain
             SQLAlchemy Core DELETE, matching the Celery-sync pattern used
             by every other Celery task in this codebase. The async
             RefreshTokenRepository.delete_expired() remains available for
             async callers (e.g. future scheduled FastAPI background tasks).
"""

from datetime import UTC

import sqlalchemy as sa

from app.celery_app import celery_app


@celery_app.task(name="auth.tasks.prune_expired_refresh_tokens")
def prune_expired_refresh_tokens() -> dict:
    """Delete refresh tokens whose expires_at is in the past.

    Run nightly via beat schedule to keep the refresh_tokens table lean.
    Returns the count of deleted rows.
    """
    from datetime import datetime

    from app.db.session import sync_session_factory
    from app.modules.auth.models import RefreshToken

    with sync_session_factory() as session:
        result = session.execute(
            sa.delete(RefreshToken).where(
                RefreshToken.expires_at < datetime.now(UTC)
            )
        )
        session.commit()
        return {"deleted": result.rowcount or 0}  # type: ignore[attr-defined]
