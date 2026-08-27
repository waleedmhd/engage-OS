"""Template model (DSD §5)."""


from typing import TYPE_CHECKING

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.constraints import enum_check
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.modules.templates.constants import TemplateCategory, TemplateStatus

if TYPE_CHECKING:
    from app.modules.campaigns.models import Campaign


class Template(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "templates"
    __table_args__ = (
        enum_check("status", TemplateStatus, "ck_templates_status_valid"),
        enum_check("category", TemplateCategory, "ck_templates_category_valid"),
        Index("ix_templates_status_category", "status", "category"),
    )

    meta_template_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=TemplateStatus.PENDING.value, index=True
    )
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=TemplateCategory.UTILITY.value
    )
    language: Mapped[str] = mapped_column(String(16), nullable=False, server_default="en")
    body: Mapped[str | None] = mapped_column(Text(), nullable=True)

    campaigns: Mapped[list["Campaign"]] = relationship("Campaign", back_populates="template")
