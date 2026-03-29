from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MarketingSurvey(Base):
    __tablename__ = "marketing_surveys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    survey_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    child_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    child_age_raw: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    child_age_years: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parent_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    residential_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    buys_on_wb: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    current_pickup_point_text: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    attraction_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    personal_data_consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    survey_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    coupon_given: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("web_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
