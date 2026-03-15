from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AdjustmentType,
    ApprovalStatus,
    EmployeePointAssignment,
    Expense,
    GeofenceException,
    MotivationRecord,
    MotivationSource,
    PayrollItem,
    PayrollRun,
    Point,
    RoleEnum,
    Shift,
    ShiftConfirmation,
    ShiftState,
    User,
    ManualAdjustment,
)


class UserRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_tg_id(self, telegram_id: int) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def list_active_employees(self) -> list[User]:
        result = await self.session.execute(
            select(User).where(User.is_active.is_(True), User.role == RoleEnum.EMPLOYEE).order_by(User.full_name)
        )
        return list(result.scalars().all())

    async def list_admins(self) -> list[User]:
        result = await self.session.execute(
            select(User).where(User.is_active.is_(True), User.role == RoleEnum.ADMIN).order_by(User.full_name)
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[User]:
        result = await self.session.execute(select(User).order_by(User.full_name))
        return list(result.scalars().all())

    async def find_by_last_name(self, last_name: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.last_name.is_not(None), User.last_name.ilike(last_name.strip()))
        )
        return result.scalar_one_or_none()

    async def create_or_update(
        self,
        telegram_id: int,
        full_name: str,
        role: RoleEnum = RoleEnum.EMPLOYEE,
        phone: str | None = None,
        manager_bonus_type: int | None = None,
    ) -> User:
        user = await self.get_by_tg_id(telegram_id)
        if user:
            user.full_name = full_name
            user.role = role
            user.is_active = True
            if phone:
                user.phone = phone
            user.last_name = self._extract_last_name(full_name)
            if manager_bonus_type is not None:
                user.manager_bonus_type = manager_bonus_type
        else:
            user = User(
                telegram_id=telegram_id,
                full_name=full_name,
                last_name=self._extract_last_name(full_name),
                role=role,
                phone=phone,
                manager_bonus_type=manager_bonus_type,
            )
            self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def set_active(self, user_id: int, is_active: bool) -> None:
        user = await self.get_by_id(user_id)
        if not user:
            return
        user.is_active = is_active
        await self.session.commit()

    async def set_active_by_tg_id(self, telegram_id: int, is_active: bool) -> Optional[User]:
        user = await self.get_by_tg_id(telegram_id)
        if not user:
            return None
        user.is_active = is_active
        await self.session.commit()
        await self.session.refresh(user)
        return user

    @staticmethod
    def _extract_last_name(full_name: str) -> str | None:
        parts = [p for p in full_name.strip().split() if p]
        return parts[0] if parts else None


class PointRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_active(self) -> list[Point]:
        result = await self.session.execute(select(Point).where(Point.is_active.is_(True)).order_by(Point.name))
        return list(result.scalars().all())

    async def list_all(self) -> list[Point]:
        result = await self.session.execute(select(Point).order_by(Point.name))
        return list(result.scalars().all())

    async def get_by_id(self, point_id: int) -> Optional[Point]:
        result = await self.session.execute(select(Point).where(Point.id == point_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Optional[Point]:
        result = await self.session.execute(select(Point).where(Point.name == name))
        return result.scalar_one_or_none()

    async def create_or_update(self, **kwargs) -> Point:
        name = kwargs["name"]
        point = await self.get_by_name(name)
        if point:
            for key, value in kwargs.items():
                setattr(point, key, value)
        else:
            point = Point(**kwargs)
            self.session.add(point)
        await self.session.commit()
        await self.session.refresh(point)
        return point

    async def set_active(self, point_id: int, is_active: bool) -> Optional[Point]:
        point = await self.get_by_id(point_id)
        if not point:
            return None
        point.is_active = is_active
        await self.session.commit()
        await self.session.refresh(point)
        return point


class AssignmentRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def assign_user_to_point(
        self,
        user_id: int,
        point_id: int,
        shift_rate_rub: Decimal,
        hourly_rate_rub: Decimal | None = None,
        is_primary: bool = False,
    ) -> EmployeePointAssignment:
        result = await self.session.execute(
            select(EmployeePointAssignment).where(
                EmployeePointAssignment.user_id == user_id,
                EmployeePointAssignment.point_id == point_id,
            )
        )
        assignment = result.scalar_one_or_none()
        if assignment:
            assignment.shift_rate_rub = shift_rate_rub
            assignment.hourly_rate_rub = hourly_rate_rub
            assignment.is_primary = is_primary
            assignment.is_active = True
        else:
            assignment = EmployeePointAssignment(
                user_id=user_id,
                point_id=point_id,
                shift_rate_rub=shift_rate_rub,
                hourly_rate_rub=hourly_rate_rub,
                is_primary=is_primary,
                is_active=True,
            )
            self.session.add(assignment)
        if is_primary:
            await self._drop_other_primaries(user_id=user_id, keep_point_id=point_id)
        await self.session.commit()
        await self.session.refresh(assignment)
        return assignment

    async def list_user_assignments(self, user_id: int) -> list[EmployeePointAssignment]:
        result = await self.session.execute(
            select(EmployeePointAssignment)
            .where(EmployeePointAssignment.user_id == user_id, EmployeePointAssignment.is_active.is_(True))
            .order_by(EmployeePointAssignment.is_primary.desc())
        )
        return list(result.scalars().all())

    async def get_assignment(self, user_id: int, point_id: int) -> Optional[EmployeePointAssignment]:
        result = await self.session.execute(
            select(EmployeePointAssignment).where(
                EmployeePointAssignment.user_id == user_id,
                EmployeePointAssignment.point_id == point_id,
                EmployeePointAssignment.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_point(self, point_id: int) -> list[EmployeePointAssignment]:
        result = await self.session.execute(
            select(EmployeePointAssignment).where(
                EmployeePointAssignment.point_id == point_id,
                EmployeePointAssignment.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def list_all_active(self) -> list[EmployeePointAssignment]:
        result = await self.session.execute(
            select(EmployeePointAssignment).where(EmployeePointAssignment.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def set_active_by_user(self, user_id: int, is_active: bool) -> None:
        result = await self.session.execute(
            select(EmployeePointAssignment).where(EmployeePointAssignment.user_id == user_id)
        )
        for assignment in result.scalars().all():
            assignment.is_active = is_active
        await self.session.commit()

    async def set_active_by_point(self, point_id: int, is_active: bool) -> None:
        result = await self.session.execute(
            select(EmployeePointAssignment).where(EmployeePointAssignment.point_id == point_id)
        )
        for assignment in result.scalars().all():
            assignment.is_active = is_active
        await self.session.commit()

    async def _drop_other_primaries(self, user_id: int, keep_point_id: int) -> None:
        result = await self.session.execute(
            select(EmployeePointAssignment).where(
                EmployeePointAssignment.user_id == user_id,
                EmployeePointAssignment.point_id != keep_point_id,
            )
        )
        for assignment in result.scalars().all():
            assignment.is_primary = False


class ConfirmationRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, user_id: int, for_date: date, status) -> ShiftConfirmation:
        result = await self.session.execute(
            select(ShiftConfirmation).where(ShiftConfirmation.user_id == user_id, ShiftConfirmation.for_date == for_date)
        )
        confirmation = result.scalar_one_or_none()
        now = datetime.utcnow()
        if confirmation:
            confirmation.status = status
            confirmation.responded_at = now
        else:
            confirmation = ShiftConfirmation(
                user_id=user_id,
                for_date=for_date,
                status=status,
                responded_at=now,
            )
            self.session.add(confirmation)
        await self.session.commit()
        await self.session.refresh(confirmation)
        return confirmation

    async def get_user_confirmation(self, user_id: int, for_date: date) -> Optional[ShiftConfirmation]:
        result = await self.session.execute(
            select(ShiftConfirmation).where(ShiftConfirmation.user_id == user_id, ShiftConfirmation.for_date == for_date)
        )
        return result.scalar_one_or_none()

    async def get_unconfirmed_employee_ids(self, for_date: date, active_employee_ids: Iterable[int]) -> list[int]:
        ids = list(active_employee_ids)
        if not ids:
            return []
        result = await self.session.execute(
            select(ShiftConfirmation.user_id).where(
                ShiftConfirmation.for_date == for_date,
                ShiftConfirmation.user_id.in_(ids),
            )
        )
        confirmed = set(result.scalars().all())
        return [user_id for user_id in ids if user_id not in confirmed]

    async def summary(self, for_date: date) -> list[ShiftConfirmation]:
        result = await self.session.execute(
            select(ShiftConfirmation).where(ShiftConfirmation.for_date == for_date).order_by(ShiftConfirmation.user_id)
        )
        return list(result.scalars().all())


class ShiftRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_open_shift(self, user_id: int) -> Optional[Shift]:
        result = await self.session.execute(
            select(Shift).where(Shift.user_id == user_id, Shift.state == ShiftState.OPEN).order_by(Shift.opened_at.desc())
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, shift_id: int) -> Optional[Shift]:
        result = await self.session.execute(select(Shift).where(Shift.id == shift_id))
        return result.scalar_one_or_none()

    async def create_open_shift(
        self,
        user_id: int,
        point_id: int,
        shift_date: date,
        opened_at: datetime,
        open_lat: float,
        open_lon: float,
        open_distance_m: float,
        open_geo_status,
        open_approval_status,
    ) -> Shift:
        shift = Shift(
            user_id=user_id,
            point_id=point_id,
            shift_date=shift_date,
            opened_at=opened_at,
            open_lat=open_lat,
            open_lon=open_lon,
            open_distance_m=open_distance_m,
            open_geo_status=open_geo_status,
            open_approval_status=open_approval_status,
            state=ShiftState.OPEN,
        )
        self.session.add(shift)
        await self.session.commit()
        await self.session.refresh(shift)
        return shift

    async def close_shift(
        self,
        shift: Shift,
        closed_at: datetime,
        close_lat: float,
        close_lon: float,
        close_distance_m: float,
        close_geo_status,
        close_approval_status,
    ) -> Shift:
        shift.closed_at = closed_at
        shift.close_lat = close_lat
        shift.close_lon = close_lon
        shift.close_distance_m = close_distance_m
        shift.close_geo_status = close_geo_status
        shift.close_approval_status = close_approval_status
        shift.state = ShiftState.CLOSED

        delta = closed_at - shift.opened_at
        shift.duration_minutes = max(0, int(delta.total_seconds() // 60))
        await self.session.commit()
        await self.session.refresh(shift)
        return shift

    async def list_user_shifts(self, user_id: int, limit: int = 10) -> list[Shift]:
        result = await self.session.execute(
            select(Shift).where(Shift.user_id == user_id).order_by(Shift.shift_date.desc(), Shift.opened_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def list_closed_between(self, period_start: date, period_end: date) -> list[Shift]:
        result = await self.session.execute(
            select(Shift).where(
                Shift.state == ShiftState.CLOSED,
                Shift.shift_date >= period_start,
                Shift.shift_date <= period_end,
            )
        )
        return list(result.scalars().all())

    async def list_by_date_point(self, shift_date: date, point_id: int) -> list[Shift]:
        result = await self.session.execute(
            select(Shift).where(
                Shift.state == ShiftState.CLOSED,
                Shift.shift_date == shift_date,
                Shift.point_id == point_id,
            )
        )
        return list(result.scalars().all())

    async def list_overdue_open(self, before_dt: datetime) -> list[Shift]:
        result = await self.session.execute(
            select(Shift).where(Shift.state == ShiftState.OPEN, Shift.opened_at <= before_dt).order_by(Shift.opened_at)
        )
        return list(result.scalars().all())

    async def update_open_approval(self, shift_id: int, status: ApprovalStatus) -> None:
        shift = await self.get_by_id(shift_id)
        if not shift:
            return
        shift.open_approval_status = status
        await self.session.commit()

    async def update_close_approval(self, shift_id: int, status: ApprovalStatus) -> None:
        shift = await self.get_by_id(shift_id)
        if not shift:
            return
        shift.close_approval_status = status
        await self.session.commit()


class GeofenceExceptionRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, shift_id: int, event: str, distance_m: float) -> GeofenceException:
        ge = GeofenceException(
            shift_id=shift_id,
            event=event,
            distance_m=distance_m,
            status=ApprovalStatus.PENDING,
        )
        self.session.add(ge)
        await self.session.commit()
        await self.session.refresh(ge)
        return ge

    async def get_by_id(self, ge_id: int) -> Optional[GeofenceException]:
        result = await self.session.execute(select(GeofenceException).where(GeofenceException.id == ge_id))
        return result.scalar_one_or_none()

    async def list_pending(self) -> list[GeofenceException]:
        result = await self.session.execute(
            select(GeofenceException)
            .where(GeofenceException.status == ApprovalStatus.PENDING)
            .order_by(GeofenceException.created_at)
        )
        return list(result.scalars().all())

    async def set_status(self, ge_id: int, status: ApprovalStatus, reviewed_by: int, reason: str | None = None) -> None:
        ge = await self.get_by_id(ge_id)
        if not ge:
            return
        ge.status = status
        ge.reviewed_by = reviewed_by
        ge.reviewed_at = datetime.utcnow()
        ge.reason = reason
        await self.session.commit()


class MotivationRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def clear_source_in_period(
        self,
        source: MotivationSource,
        period_start: date,
        period_end: date,
    ) -> None:
        await self.session.execute(
            delete(MotivationRecord).where(
                MotivationRecord.source == source,
                MotivationRecord.record_date >= period_start,
                MotivationRecord.record_date <= period_end,
            )
        )
        await self.session.commit()

    async def add_many(self, records: list[MotivationRecord]) -> None:
        self.session.add_all(records)
        await self.session.commit()

    async def list_between(self, period_start: date, period_end: date) -> list[MotivationRecord]:
        result = await self.session.execute(
            select(MotivationRecord).where(
                MotivationRecord.record_date >= period_start,
                MotivationRecord.record_date <= period_end,
            )
        )
        return list(result.scalars().all())

    async def list_between_source(
        self,
        source: MotivationSource,
        period_start: date,
        period_end: date,
    ) -> list[MotivationRecord]:
        result = await self.session.execute(
            select(MotivationRecord).where(
                MotivationRecord.source == source,
                MotivationRecord.record_date >= period_start,
                MotivationRecord.record_date <= period_end,
            )
        )
        return list(result.scalars().all())

    async def list_user_source_in_period(
        self,
        user_id: int,
        source: MotivationSource,
        period_start: date,
        period_end: date,
    ) -> list[MotivationRecord]:
        result = await self.session.execute(
            select(MotivationRecord).where(
                MotivationRecord.user_id == user_id,
                MotivationRecord.source == source,
                MotivationRecord.record_date >= period_start,
                MotivationRecord.record_date <= period_end,
            )
        )
        return list(result.scalars().all())


class ManualAdjustmentRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        user_id: int,
        period_start: date,
        period_end: date,
        amount_rub: Decimal,
        adjustment_type: AdjustmentType,
        comment: str | None,
        created_by: int | None,
    ) -> ManualAdjustment:
        row = ManualAdjustment(
            user_id=user_id,
            period_start=period_start,
            period_end=period_end,
            amount_rub=amount_rub,
            adjustment_type=adjustment_type,
            comment=comment,
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_for_period(self, period_start: date, period_end: date) -> list[ManualAdjustment]:
        result = await self.session.execute(
            select(ManualAdjustment).where(
                # Пересечение диапазонов
                ManualAdjustment.period_start <= period_end,
                ManualAdjustment.period_end >= period_start,
            )
        )
        return list(result.scalars().all())


class ExpenseRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(
        self,
        point_id: int,
        expense_date: date,
        amount_rub: Decimal,
        category: str,
        description: str | None,
        created_by: int | None,
    ) -> Expense:
        row = Expense(
            point_id=point_id,
            expense_date=expense_date,
            amount_rub=amount_rub,
            category=category,
            description=description,
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_period(self, period_start: date, period_end: date) -> list[Expense]:
        result = await self.session.execute(
            select(Expense)
            .where(Expense.expense_date >= period_start, Expense.expense_date <= period_end)
            .order_by(Expense.expense_date.desc())
        )
        return list(result.scalars().all())


class PayrollRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_run(self, period_start: date, period_end: date, payout_day: int) -> Optional[PayrollRun]:
        result = await self.session.execute(
            select(PayrollRun).where(
                PayrollRun.period_start == period_start,
                PayrollRun.period_end == period_end,
                PayrollRun.payout_day == payout_day,
            )
        )
        return result.scalar_one_or_none()

    async def create_or_replace_run(
        self,
        period_start: date,
        period_end: date,
        payout_day: int,
        generated_by: int | None,
    ) -> PayrollRun:
        run = await self.get_run(period_start=period_start, period_end=period_end, payout_day=payout_day)
        if run:
            await self.session.execute(delete(PayrollItem).where(PayrollItem.run_id == run.id))
        else:
            run = PayrollRun(
                period_start=period_start,
                period_end=period_end,
                payout_day=payout_day,
                generated_by=generated_by,
            )
            self.session.add(run)
            await self.session.flush()
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def add_items(self, items: list[PayrollItem]) -> None:
        self.session.add_all(items)
        await self.session.commit()

    async def list_run_items(self, run_id: int) -> list[PayrollItem]:
        result = await self.session.execute(select(PayrollItem).where(PayrollItem.run_id == run_id))
        return list(result.scalars().all())

    async def latest_user_item(self, user_id: int) -> Optional[PayrollItem]:
        result = await self.session.execute(
            select(PayrollItem)
            .where(PayrollItem.user_id == user_id)
            .order_by(PayrollItem.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_runs(self, limit: int = 10) -> list[PayrollRun]:
        result = await self.session.execute(select(PayrollRun).order_by(PayrollRun.generated_at.desc()).limit(limit))
        return list(result.scalars().all())
