from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PointDeliveryStat(Base):
    __tablename__ = "point_delivery_stats"
    __table_args__ = (
        UniqueConstraint("point_id", "stat_date", name="uq_point_delivery_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    point_id: Mapped[int] = mapped_column(
        ForeignKey("points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    night_raw: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    night_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    morning_raw: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    morning_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    day_raw: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    day_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    evening_raw: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    evening_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
