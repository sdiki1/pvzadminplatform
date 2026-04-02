from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RoleEnum(str, Enum):
    EMPLOYEE = "employee"
    ADMIN = "admin"


class BrandEnum(str, Enum):
    WB = "wb"
    OZON = "ozon"


class ConfirmationStatus(str, Enum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class GeoStatus(str, Enum):
    OK = "ok"
    OUTSIDE = "outside"


class ApprovalStatus(str, Enum):
    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


class ShiftState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class AdjustmentType(str, Enum):
    BONUS = "bonus"
    DEDUCTION = "deduction"
    CORRECTION = "correction"


class MotivationSource(str, Enum):
    MAIN = "main"
    DISPUTE = "dispute"
    OZON = "ozon"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    role: Mapped[RoleEnum] = mapped_column(SqlEnum(RoleEnum), default=RoleEnum.EMPLOYEE, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # 1/2/3 - для доп. начислений в выплате 10-го числа
    manager_bonus_type: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Персональные ставки сотрудника (применяются во всех точках)
    shift_rate_rub: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"), nullable=False)
    hourly_rate_rub: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    # Цвет в календаре (hex, например #3b82f6)
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    assignments: Mapped[list[EmployeePointAssignment]] = relationship(back_populates="user")
    shifts: Mapped[list[Shift]] = relationship(back_populates="user")


class Point(Base):
    __tablename__ = "points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[BrandEnum] = mapped_column(SqlEnum(BrandEnum), nullable=False)

    latitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    radius_m: Mapped[int] = mapped_column(Integer, default=150, nullable=False)

    work_start: Mapped[time] = mapped_column(Time, nullable=False)
    work_end: Mapped[time] = mapped_column(Time, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # New fields for web admin
    marketplace_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("marketplaces.id", ondelete="SET NULL"), nullable=True
    )
    short_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    address_normalized: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, onupdate=datetime.utcnow)

    assignments: Mapped[list[EmployeePointAssignment]] = relationship(back_populates="point")
    shifts: Mapped[list[Shift]] = relationship(back_populates="point")


class EmployeePointAssignment(Base):
    __tablename__ = "employee_point_assignments"
    __table_args__ = (UniqueConstraint("user_id", "point_id", name="uq_user_point"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    point_id: Mapped[int] = mapped_column(ForeignKey("points.id", ondelete="CASCADE"), nullable=False)

    shift_rate_rub: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"), nullable=False)
    hourly_rate_rub: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)

    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="assignments")
    point: Mapped[Point] = relationship(back_populates="assignments")


class ShiftConfirmation(Base):
    __tablename__ = "shift_confirmations"
    __table_args__ = (UniqueConstraint("user_id", "for_date", name="uq_user_confirm_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    for_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[ConfirmationStatus] = mapped_column(SqlEnum(ConfirmationStatus), nullable=False)
    responded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    point_id: Mapped[int] = mapped_column(ForeignKey("points.id", ondelete="CASCADE"), nullable=False, index=True)

    shift_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    state: Mapped[ShiftState] = mapped_column(SqlEnum(ShiftState), default=ShiftState.OPEN, nullable=False)

    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open_lat: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    open_lon: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    open_distance_m: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    open_geo_status: Mapped[GeoStatus] = mapped_column(SqlEnum(GeoStatus), nullable=False)
    open_approval_status: Mapped[ApprovalStatus] = mapped_column(
        SqlEnum(ApprovalStatus), default=ApprovalStatus.APPROVED, nullable=False
    )

    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    close_lat: Mapped[Optional[float]] = mapped_column(Numeric(10, 7), nullable=True)
    close_lon: Mapped[Optional[float]] = mapped_column(Numeric(10, 7), nullable=True)
    close_distance_m: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    close_geo_status: Mapped[Optional[GeoStatus]] = mapped_column(SqlEnum(GeoStatus), nullable=True)
    close_approval_status: Mapped[Optional[ApprovalStatus]] = mapped_column(SqlEnum(ApprovalStatus), nullable=True)

    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="shifts")
    point: Mapped[Point] = relationship(back_populates="shifts")


class ManualAdjustment(Base):
    __tablename__ = "manual_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    amount_rub: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    adjustment_type: Mapped[AdjustmentType] = mapped_column(SqlEnum(AdjustmentType), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class MotivationRecord(Base):
    __tablename__ = "motivation_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[MotivationSource] = mapped_column(SqlEnum(MotivationSource), nullable=False, index=True)

    record_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    point_id: Mapped[Optional[int]] = mapped_column(ForeignKey("points.id", ondelete="SET NULL"), nullable=True, index=True)

    # Храним и user_id, и manager_name для гибкой сопоставимости
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    manager_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    acceptance_amount_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    issued_items_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tickets_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    disputed_amount_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)

    status: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    raw_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    point_id: Mapped[int] = mapped_column(ForeignKey("points.id", ondelete="CASCADE"), nullable=False, index=True)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    amount_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PayrollRun(Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (
        UniqueConstraint("period_start", "period_end", "payout_day", name="uq_payroll_period_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payout_day: Mapped[int] = mapped_column(Integer, nullable=False)

    generated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PayrollItem(Base):
    __tablename__ = "payroll_items"
    __table_args__ = (UniqueConstraint("run_id", "user_id", name="uq_payroll_run_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    shifts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hours_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"), nullable=False)

    base_amount_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    motivation_amount_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    rating_bonus_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    issued_bonus_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    reserve_bonus_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    substitution_bonus_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    stuck_deduction_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    substitution_deduction_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    defect_deduction_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    dispute_deduction_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    manager_bonus_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    adjustments_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    debt_adjustment_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    total_amount_rub: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)

    details_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PlannedShift(Base):
    """Shift scheduled via web admin (not yet opened by the employee via bot)."""

    __tablename__ = "planned_shifts"
    __table_args__ = (UniqueConstraint("user_id", "shift_date", name="uq_planned_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    point_id: Mapped[int] = mapped_column(ForeignKey("points.id", ondelete="CASCADE"), nullable=False, index=True)
    shift_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Почасовой план смены (если не задано, считается смена на весь день)
    start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    # Резервное дежурство (+400 ₽ за дежурство)
    is_reserve: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Подмена на выходе (+500 ₽ за фактически отработанный выход)
    is_substitution: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped[User] = relationship()
    point: Mapped[Point] = relationship()


class GeofenceException(Base):
    __tablename__ = "geofence_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(16), nullable=False)  # open/close
    distance_m: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    status: Mapped[ApprovalStatus] = mapped_column(SqlEnum(ApprovalStatus), default=ApprovalStatus.PENDING, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
