from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WebRoleEnum(str, Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    MANAGER = "manager"
    SENIOR = "senior"
    EMPLOYEE = "employee"
    DISPUTES = "disputes"
    MARKETING = "marketing"
    VIEWER = "viewer"


class WebUser(Base):
    __tablename__ = "web_users"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_web_user_employee"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # JSON array of role strings, e.g. '["manager","disputes"]'
    roles_json: Mapped[str] = mapped_column(Text, default='["viewer"]', nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    employee: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id], lazy="select")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    @property
    def roles(self) -> list[str]:
        """Return the list of role strings."""
        try:
            return json.loads(self.roles_json)
        except Exception:
            return ["viewer"]

    @property
    def role(self) -> str:
        """Primary role (first in list) — kept for backward compatibility."""
        r = self.roles
        return r[0] if r else "viewer"

    def has_role(self, *role_values: str) -> bool:
        """Return True if the user has any of the given roles."""
        return bool(set(self.roles).intersection(role_values))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    before_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("web_users.id", ondelete="SET NULL"), nullable=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class EmailConfirmation(Base):
    """One-time codes for critical admin operations, sent to admin email."""

    __tablename__ = "email_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    web_user_id: Mapped[int] = mapped_column(
        ForeignKey("web_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    # serialised payload to replay after confirmation (e.g. form data as JSON)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_email_conf_user_op", "web_user_id", "operation"),
    )
