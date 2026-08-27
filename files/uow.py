"""
app/db/uow.py

Fixes applied:
  DB-M5 — UnitOfWork.__aenter__ did not call session.begin(), so the
           transaction was started implicitly on first query. When used
           alongside the transactional() decorator, this produced a
           SAVEPOINT on top of an implicit transaction instead of a
           real nested transaction boundary. Behaviour was unpredictable
           and difficult to reason about across callers.

           Fix: session.begin() is called explicitly in __aenter__ to
           establish a clear outer transaction boundary.

  DB-M4 — If commit() itself raised (e.g. serialisation failure, FK
           violation surfacing at commit time), the session was closed
           without an explicit rollback. SQLAlchemy rolls back implicitly
           on session close, but any rollback-event hooks registered on
           the session were skipped.

           Fix: commit() is wrapped in try/except; on any exception the
           session is explicitly rolled back before being closed, ensuring
           all registered hooks fire.
"""
from __future__ import annotations

import contextlib
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory


class UnitOfWork:
    """
    Async Unit of Work.

    Provides a single transactional session for a logical operation.
    Use this for multi-step write operations that must succeed or fail
    atomically.

    Usage:
        async with UnitOfWork() as uow:
            repo = ConversationRepository(uow.session)
            conv = await repo.get_or_404(conv_id)
            await repo.update_state(conv.id, ...)
            # session.commit() is called automatically on clean __aexit__

    For single-operation writes, prefer the transactional() context manager.
    """

    def __init__(self) -> None:
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "UnitOfWork":
        self._session = async_session_factory()
        # DB-M5 fix: begin() establishes an explicit transaction boundary.
        # Without this, the first query auto-begins an implicit transaction,
        # and mixing with transactional() produces unexpected SAVEPOINT nesting.
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        assert self._session is not None, "UnitOfWork exited before being entered"
        try:
            if exc_type is None:
                # DB-M4 fix: commit() is inside try/except so that if it
                # raises (e.g. IntegrityError surfacing at flush, or a
                # serialisation failure), we explicitly roll back before
                # closing. This guarantees that rollback event hooks fire.
                try:
                    await self._session.commit()
                except Exception:
                    await self._session.rollback()
                    raise
            else:
                await self._session.rollback()
        finally:
            await self._session.close()

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError(
                "UnitOfWork.session accessed before entering context. "
                "Use 'async with UnitOfWork() as uow'."
            )
        return self._session


@contextlib.asynccontextmanager
async def transactional() -> AsyncGenerator[AsyncSession, None]:
    """
    Convenience context manager for single-scope transactions.

    Internally uses UnitOfWork, so all the same guarantees apply
    (explicit begin, explicit rollback on commit failure).

    Usage:
        async with transactional() as session:
            repo = ContactRepository(session)
            await repo.create(phone="+971...")
    """
    async with UnitOfWork() as uow:
        yield uow.session
