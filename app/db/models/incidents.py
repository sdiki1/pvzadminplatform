from __future__ import annotations

from datetime import date, datetime, time
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
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DefectIncident(Base):
    __tablename__ = "defect_incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    point_id: Mapped[int] = mapped_column(
        ForeignKey("points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    incident_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    incident_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)

    # Кто обнаружил: client / employee / unknown / other
    detected_by_role: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    # На каком этапе: intake / issue / receipt / check / return / return_home / other
    detected_stage: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
    detected_source_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Тип: defect / mismatch / substitution / spill / damage / incomplete_set / other
    incident_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    barcode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    product_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    problem_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    full_description_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Что сделал сотрудник
    action_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    action_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    recorded_by_employee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # new / in_progress / closed / cancelled
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="new", index=True)
    resolution_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
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


class SOSIncident(Base):
    __tablename__ = "sos_incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    point_id: Mapped[int] = mapped_column(
        ForeignKey("points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    incident_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    incident_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)

    cell_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    description: Mapped[str] = mapped_column(Text, nullable=False)
    products_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)

    recorded_by_employee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    responsible_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("web_users.id", ondelete="SET NULL"), nullable=True
    )

    # open / resolved / unresolved / on_hold
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open", index=True)
    resolution_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    linked_defect_incident_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("defect_incidents.id", ondelete="SET NULL"), nullable=True
    )
    linked_appeal_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
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
