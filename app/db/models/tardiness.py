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


class TardinessRecord(Base):
    """Automatically detected or manually created tardiness record for a shift."""

    __tablename__ = "tardiness_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shift_id: Mapped[int] = mapped_column(
        ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    point_id: Mapped[int] = mapped_column(
        ForeignKey("points.id", ondelete="SET NULL"), nullable=True
    )
    shift_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Planned work start (from point.work_start at shift_date)
    planned_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Actual shift open time
    actual_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Delay in minutes (actual - planned, positive = late)
    delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Fine amount in RUB (0 if excused)
    fine_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))
    # True = fine is waived/excused by admin
    is_excused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excuse_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # FK to ManualAdjustment created for this fine (NULL until admin confirms)
    adjustment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("manual_adjustments.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("web_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
