"""Template repository — DB access only."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.repository import BaseRepository
from app.modules.templates.constants import TemplateStatus
from app.modules.templates.models import Template


class TemplateRepository(BaseRepository[Template]):
    model = Template

    async def list_with_total(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
    ) -> tuple[Sequence[Template], int]:
        base = select(Template)
        if status:
            base = base.where(Template.status == status)

        total = await self.session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        stmt = (
            base.order_by(Template.created_at.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), int(total or 0)

    async def get_by_name(self, name: str) -> Template | None:
        result = await self.session.execute(
            select(Template).where(Template.name == name)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        template_id: uuid.UUID,
        status: str,
        *,
        meta_template_id: str | None = None,
        body: str | None = None,
    ) -> Template | None:
        fields: dict = {"status": status}
        if meta_template_id is not None:
            fields["meta_template_id"] = meta_template_id
        if body is not None:
            fields["body"] = body
        return await self.update(template_id, **fields)

    async def upsert_from_meta(
        self,
        *,
        name: str,
        meta_template_id: str,
        status: str,
        category: str,
        language: str,
        body: str | None,
    ) -> Template:
        """Insert or update a template row from a Meta bulk-import.

        Uses ``name`` as the natural key (Meta names are immutable once
        submitted). If a row already exists it is updated in-place; otherwise
        a new row is created.
        """
        existing = await self.get_by_name(name)
        if existing is not None:
            existing.meta_template_id = meta_template_id
            existing.status = status
            existing.category = category
            existing.language = language
            if body is not None:
                existing.body = body
            return existing

        template = Template(
            name=name,
            meta_template_id=meta_template_id,
            status=status,
            category=category,
            language=language,
            body=body,
        )
        self.session.add(template)
        return template

    # ---------------------------------------------------------- sync mirrors
    # Used by the Celery on-demand status-sync task (sync session).

    @staticmethod
    def get_sync(session: Session, template_id: uuid.UUID) -> Template | None:
        return session.get(Template, template_id)

    @staticmethod
    def update_status_sync(
        session: Session, template_id: uuid.UUID, status: str
    ) -> Template | None:
        tmpl = session.get(Template, template_id)
        if tmpl is None:
            return None
        tmpl.status = status
        session.flush()
        return tmpl

    @staticmethod
    def list_unresolved_sync(session: Session) -> Sequence[Template]:
        """Templates still awaiting a terminal Meta decision (have a remote id)."""
        stmt = select(Template).where(
            Template.status == TemplateStatus.PENDING.value,
            Template.meta_template_id.is_not(None),
        )
        return session.execute(stmt).scalars().all()
