from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Appeal(Base):
    __tablename__ = "appeals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    point_id: Mapped[int] = mapped_column(
        ForeignKey("points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # defect / substitution / stuck / other
    appeal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    barcode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    ticket_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)

    # none / in_progress / appealed / not_appealed / closed
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="none", index=True)
    assigned_manager_employee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_manager_raw: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    non_appeal_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    charge_to_manager: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    charge_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feedback_from_nadezhda: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feedback_from_anna: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deadline_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    result_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("web_users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("web_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class AppealFeedback(Base):
    __tablename__ = "appeal_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appeal_id: Mapped[int] = mapped_column(
        ForeignKey("appeals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewer_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("web_users.id", ondelete="SET NULL"), nullable=True
    )
    reviewer_role: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
