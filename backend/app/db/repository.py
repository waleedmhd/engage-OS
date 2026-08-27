"""
app/db/repository.py

Fixes applied:
  DB-C3  — BaseRepository.update previously issued UPDATE...RETURNING which
            bypassed SQLAlchemy's identity map. Any other reference to the
            same row already loaded in the session would retain its pre-update
            state for the lifetime of the UoW, causing silent wrong reads.

            Fix: update is now performed via ORM attribute assignment on the
            already-loaded instance. session.flush() propagates the change to
            the DB; session.refresh() re-queries the row so the identity map
            reflects the committed columns (including server-side defaults such
            as updated_at).

  DB-M6  — list(order_by=...) accepted relationship names, causing opaque
            ORM errors at query time instead of a clear ValueError.
            Fix: relationship keys are explicitly rejected before building stmt.

  DB-M7  — count() used select_from(model) directly; this pattern breaks when
            future joins add rows. Fix: count wraps the filtered select as a
            subquery so the count is always over distinct model rows.

  DB-M15 — update() returned None for both "row not found" and "no fields
            supplied". Callers could not distinguish the two cases.
            Fix: empty kwargs returns the unmodified instance immediately
            (no flush); missing row returns None.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError

ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    """
    Generic async repository.

    Subclasses must declare `model: type[ModelT]` as a class attribute.

    Example:
        class ConversationRepository(BaseRepository[Conversation]):
            model = Conversation
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ reads

    async def get(self, id: uuid.UUID) -> ModelT | None:
        """Return the instance by primary key, or None if not found."""
        return await self.session.get(self.model, id)

    async def get_or_404(self, id: uuid.UUID) -> ModelT:
        """Return the instance by primary key, or raise NotFoundError."""
        instance = await self.get(id)
        if instance is None:
            raise NotFoundError(f"{self.model.__name__} {id} not found")
        return instance

    async def list(
        self,
        *,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[ModelT]:
        """
        DB-M6 fix: validate order_by is a column (not a relationship)
        before executing the query, so callers get a clear ValueError
        instead of a cryptic ORM error.
        """
        stmt = sa.select(self.model)

        if filters:
            for column_name, value in filters.items():
                col = self._get_column_or_raise(column_name)
                stmt = stmt.where(col == value)

        if order_by is not None:
            col = self._get_column_or_raise(order_by)
            self._assert_not_relationship(order_by)
            stmt = stmt.order_by(col)

        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, filters: dict[str, Any] | None = None) -> int:
        """
        DB-M7 fix: wraps the filtered select as a subquery before
        applying COUNT(*) so the count survives future joins without
        double-counting rows.
        """
        inner = sa.select(self.model)

        if filters:
            for column_name, value in filters.items():
                col = self._get_column_or_raise(column_name)
                inner = inner.where(col == value)

        stmt = sa.select(sa.func.count()).select_from(inner.subquery())
        result = await self.session.execute(stmt)
        return result.scalar_one()

    # ----------------------------------------------------------------- writes

    async def create(self, **kwargs: Any) -> ModelT:
        """
        Persist a new instance and return it fully populated (including
        server-side defaults such as id, created_at).
        """
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(
        self,
        id: uuid.UUID,
        **kwargs: Any,
    ) -> ModelT | None:
        """
        Apply keyword-argument updates to an existing row.

        DB-C3 fix: the previous implementation used:
            UPDATE ... RETURNING *
        which writes the row but does NOT invalidate other references to
        the same instance already loaded in the session. Any caller that
        held a reference before the UPDATE would continue reading stale
        data within the same Unit of Work — silently, with no error.

        This implementation uses ORM attribute assignment instead:
          1. Load the instance via session.get() (identity-map aware).
          2. Assign new values — SQLAlchemy marks the instance dirty.
          3. flush() issues the UPDATE statement.
          4. refresh() re-reads the row so server-side columns (e.g.
             updated_at via trigger) are reflected immediately.

        All existing session references to this instance now reflect the
        updated values because they all share the same identity-map entry.

        DB-M15 fix:
          - Returns None only when the row does not exist.
          - Returns the unmodified instance for empty kwargs (no-op).
        """
        instance = await self.get(id)
        if instance is None:
            return None

        # DB-M15: empty kwargs is a documented no-op — return as-is.
        if not kwargs:
            return instance

        for key, value in kwargs.items():
            setattr(instance, key, value)

        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, id: uuid.UUID) -> bool:
        """Delete by primary key. Returns True if a row was deleted."""
        instance = await self.get(id)
        if instance is None:
            return False
        await self.session.delete(instance)
        await self.session.flush()
        return True

    # ---------------------------------------------------------- helper methods

    def _get_column_or_raise(self, column_name: str) -> Any:
        """
        Return the mapped column attribute or raise ValueError if it does
        not exist on the model.
        """
        col = getattr(self.model, column_name, None)
        if col is None:
            raise ValueError(
                f"'{column_name}' is not an attribute of {self.model.__name__}."
            )
        return col

    def _assert_not_relationship(self, attribute_name: str) -> None:
        """
        Raise ValueError if the named attribute is an ORM relationship.

        DB-M6 fix: SQLAlchemy silently accepts relationship attributes in
        order_by clauses, producing queries that appear to work but fail
        at execution time with cryptic errors rather than surfacing the
        mistake early.
        """
        mapper = sa.inspect(self.model)
        relationship_keys = {r.key for r in mapper.relationships}  # type: ignore[union-attr]
        if attribute_name in relationship_keys:
            raise ValueError(
                f"'{attribute_name}' is an ORM relationship on "
                f"{self.model.__name__}, not a sortable column. "
                "Pass a scalar column name instead."
            )
