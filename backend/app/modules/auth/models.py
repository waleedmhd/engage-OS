"""User and RefreshToken models.

User: all FK targets that point at `users.id` resolve here (assigned_agent_id,
locked_by, approved_by, created_by, actor_id — per DSD §6.1 / §9).
RefreshToken: opaque tokens stored as SHA-256 hashes to enable revocation.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.constraints import enum_check
from app.db.mixins import TimestampMixin, UUIDPKMixin
from app.modules.auth.constants import UserRole

if TYPE_CHECKING:
    from app.modules.contacts.models import Contact
    from app.modules.conversations.models import Conversation


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        enum_check("role", UserRole, "ck_users_role_valid"),
        Index("ix_users_role_active", "role", "is_active"),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default=UserRole.AGENT.value, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    assigned_contacts: Mapped[list["Contact"]] = relationship(
        "Contact", back_populates="assigned_agent", foreign_keys="Contact.assigned_agent_id"
    )
    locked_conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="lock_holder", foreign_keys="Conversation.locked_by"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(UUIDPKMixin, TimestampMixin, Base):
    """Opaque refresh tokens stored as SHA-256 hashes for revocation support."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_active", "user_id", "revoked"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")
