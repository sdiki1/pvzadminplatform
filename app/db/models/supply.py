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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SupplyItem(Base):
    __tablename__ = "supply_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    marketplace_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("marketplaces.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, default="шт")
    min_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class SupplyRequestHeader(Base):
    __tablename__ = "supply_request_headers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    point_id: Mapped[int] = mapped_column(
        ForeignKey("points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    requested_by_employee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # new / partially_ordered / ordered / in_transit / partially_delivered / delivered / closed / cancelled
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="new")
    plan_delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    actual_delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
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


class SupplyRequestItem(Base):
    __tablename__ = "supply_request_items"
    __table_args__ = (
        UniqueConstraint("request_id", "supply_item_id", name="uq_request_supply_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("supply_request_headers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supply_item_id: Mapped[int] = mapped_column(
        ForeignKey("supply_items.id", ondelete="CASCADE"), nullable=False
    )
    requested_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    approved_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    delivered_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    # not_needed / requested / ordered / in_transit / delivered / in_stock / cancelled
    item_status: Mapped[str] = mapped_column(String(50), nullable=False, default="requested")
    status_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    raw_status_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
