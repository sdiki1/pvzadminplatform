from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    Appeal,
    ApprovalStatus,
    MotivationSource,
    PayrollItem,
    PlannedShift,
    Shift,
    User,
)
from app.db.repositories import (
    ManualAdjustmentRepo,
    MotivationRepo,
    PayrollRepo,
    PointRepo,
    ShiftRepo,
    UserRepo,
)
from app.utils.dates import month_bounds
from app.utils.parsing import normalize_text

ZERO = Decimal("0")


@dataclass
class PayrollUserInput:
    issued_bonus_rub: Decimal | None = None
    rating_bonus_rub: Decimal = ZERO
    debt_adjustment_rub: Decimal = ZERO


@dataclass
class EmployeePayrollBreakdown:
    user: User
    shifts_count: int
    hours_total: Decimal
    base_amount_rub: Decimal
    motivation_amount_rub: Decimal
    rating_bonus_rub: Decimal
    issued_bonus_rub: Decimal
    reserve_bonus_rub: Decimal
    substitution_bonus_rub: Decimal
    stuck_deduction_rub: Decimal
    substitution_deduction_rub: Decimal
    defect_deduction_rub: Decimal
    dispute_deduction_rub: Decimal
    manager_bonus_rub: Decimal
    adjustments_rub: Decimal
    subtotal_amount_rub: Decimal
    debt_adjustment_rub: Decimal
    total_amount_rub: Decimal
    issued_items_total: Decimal
    details: dict


class PayrollService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings

        self.user_repo = UserRepo(session)
        self.point_repo = PointRepo(session)
        self.shift_repo = ShiftRepo(session)
        self.motivation_repo = MotivationRepo(session)
        self.adjustment_repo = ManualAdjustmentRepo(session)
        self.payroll_repo = PayrollRepo(session)

    async def preview_payroll(
        self,
        period_start: date,
        period_end: date,
        payout_day: int,
        user_inputs: Mapping[int | str, PayrollUserInput | Mapping[str, object]] | None = None,
    ) -> list[EmployeePayrollBreakdown]:
        return await self._calculate_rows(period_start, period_end, payout_day, user_inputs)

    async def run_payroll(
        self,
        period_start: date,
        period_end: date,
        payout_day: int,
        generated_by: int | None,
        user_inputs: Mapping[int | str, PayrollUserInput | Mapping[str, object]] | None = None,
    ) -> tuple[int, list[EmployeePayrollBreakdown]]:
        results = await self._calculate_rows(period_start, period_end, payout_day, user_inputs)

        run = await self.payroll_repo.create_or_replace_run(period_start, period_end, payout_day, generated_by)

        db_items: list[PayrollItem] = []
        for result in results:
            db_items.append(
                PayrollItem(
                    run_id=run.id,
                    user_id=result.user.id,
                    shifts_count=result.shifts_count,
                    hours_total=result.hours_total,
                    base_amount_rub=result.base_amount_rub,
                    motivation_amount_rub=result.motivation_amount_rub,
                    rating_bonus_rub=result.rating_bonus_rub,
                    issued_bonus_rub=result.issued_bonus_rub,
                    reserve_bonus_rub=result.reserve_bonus_rub,
                    substitution_bonus_rub=result.substitution_bonus_rub,
                    stuck_deduction_rub=result.stuck_deduction_rub,
                    substitution_deduction_rub=result.substitution_deduction_rub,
                    defect_deduction_rub=result.defect_deduction_rub,
                    dispute_deduction_rub=result.dispute_deduction_rub,
                    manager_bonus_rub=result.manager_bonus_rub,
                    adjustments_rub=result.adjustments_rub,
                    debt_adjustment_rub=result.debt_adjustment_rub,
                    total_amount_rub=result.total_amount_rub,
                    details_json=json.dumps(result.details, ensure_ascii=False),
                )
            )

        await self.payroll_repo.add_items(db_items)
        return run.id, results

    async def _calculate_rows(
        self,
        period_start: date,
        period_end: date,
        payout_day: int,
        user_inputs: Mapping[int | str, PayrollUserInput | Mapping[str, object]] | None,
    ) -> list[EmployeePayrollBreakdown]:
        normalized_user_inputs = self._normalize_user_inputs(user_inputs)

        users = await self.user_repo.list_active_employees()
        users_map = {u.id: u for u in users}

        points = await self.point_repo.list_all()
        points_map = {p.id: p for p in points}

        shifts = await self.shift_repo.list_closed_between(period_start, period_end)
        valid_shifts = [s for s in shifts if self._is_shift_payable(s)]
        planned_result = await self.session.execute(
            select(PlannedShift).where(
                PlannedShift.shift_date >= period_start,
                PlannedShift.shift_date <= period_end,
            )
        )
        planned_shifts = planned_result.scalars().all()

        main_records = await self.motivation_repo.list_between_source(MotivationSource.MAIN, period_start, period_end)
        dispute_records = await self.motivation_repo.list_between_source(MotivationSource.DISPUTE, period_start, period_end)
        adjustments = await self.adjustment_repo.list_for_period(period_start, period_end)

        shift_hours_by_user = defaultdict(lambda: ZERO)
        shifts_count_by_user = defaultdict(int)
        base_by_user = defaultdict(lambda: ZERO)
        reserve_count_by_user = defaultdict(int)
        substitution_count_by_user = defaultdict(int)

        shifts_by_day_point: dict[tuple[date, int], list[Shift]] = defaultdict(list)
        for shift in valid_shifts:
            shifts_by_day_point[(shift.shift_date, shift.point_id)].append(shift)

            hours = self._shift_hours(shift)
            shift_hours_by_user[shift.user_id] += hours
            shifts_count_by_user[shift.user_id] += 1

            user = users_map.get(shift.user_id)
            if not user:
                continue
            point = points_map.get(shift.point_id)
            base_by_user[shift.user_id] += self._calc_shift_base(shift, user, point)

        substitution_plan_keys: set[tuple[int, date, int]] = set()
        for ps in planned_shifts:
            if ps.is_reserve:
                reserve_count_by_user[ps.user_id] += 1
            if ps.is_substitution:
                substitution_plan_keys.add((ps.user_id, ps.shift_date, ps.point_id))

        for shift in valid_shifts:
            if (shift.user_id, shift.shift_date, shift.point_id) in substitution_plan_keys:
                substitution_count_by_user[shift.user_id] += 1

        user_id_by_last_name: dict[str, int] = {}
        for user in users:
            if user.last_name:
                user_id_by_last_name[normalize_text(user.last_name)] = user.id

        motivation_by_user = defaultdict(lambda: ZERO)
        issued_count_by_user = defaultdict(lambda: ZERO)
        tickets_by_user = defaultdict(lambda: ZERO)

        for rec in main_records:
            self._distribute_main_record(
                record=rec,
                shifts_by_day_point=shifts_by_day_point,
                user_id_by_last_name=user_id_by_last_name,
                motivation_by_user=motivation_by_user,
                issued_count_by_user=issued_count_by_user,
                tickets_by_user=tickets_by_user,
            )

        stuck_deduction_by_user = defaultdict(lambda: ZERO)
        substitution_deduction_by_user = defaultdict(lambda: ZERO)
        defect_deduction_by_user = defaultdict(lambda: ZERO)

        appeals_result = await self.session.execute(
            select(Appeal).where(
                Appeal.case_date >= period_start,
                Appeal.case_date <= period_end,
            )
        )
        appeals = appeals_result.scalars().all()

        appeal_deductions_found = False
        for appeal in appeals:
            user_id = appeal.assigned_manager_employee_id or self._match_user_id_from_name(
                appeal.assigned_manager_raw, user_id_by_last_name
            )
            if not user_id:
                continue
            if not self._is_appeal_deduction(appeal):
                continue
            amount = abs(Decimal(appeal.amount or 0))
            if amount <= 0:
                continue
            appeal_deductions_found = True

            appeal_type = normalize_text(appeal.appeal_type or "")
            if "stuck" in appeal_type or "завис" in appeal_type:
                stuck_deduction_by_user[user_id] += amount
            elif "substitution" in appeal_type or "подмен" in appeal_type:
                substitution_deduction_by_user[user_id] += amount
            elif "defect" in appeal_type or "брак" in appeal_type:
                defect_deduction_by_user[user_id] += amount
            else:
                defect_deduction_by_user[user_id] += amount

        # Backward compatibility: if appeal deductions are absent,
        # use historical dispute motivation records.
        if not appeal_deductions_found:
            for rec in dispute_records:
                status = normalize_text(rec.status or "")
                if "не оспор" not in status and "not_appealed" not in status:
                    continue
                user_id = rec.user_id or self._match_user_id_from_name(rec.manager_name, user_id_by_last_name)
                if not user_id:
                    continue
                defect_deduction_by_user[user_id] += abs(Decimal(rec.disputed_amount_rub or 0))

        adjustments_by_user = defaultdict(lambda: ZERO)
        for adj in adjustments:
            amount = Decimal(adj.amount_rub)
            if adj.adjustment_type.value == "deduction":
                amount = -abs(amount)
            elif adj.adjustment_type.value == "bonus":
                amount = abs(amount)
            adjustments_by_user[adj.user_id] += amount

        manager_bonus_by_user = defaultdict(lambda: ZERO)
        if payout_day == 10:
            manager_bonus_by_user = await self._calc_manager_bonus_for_tenth(period_end, users_map, user_id_by_last_name)

        issued_bonus_by_user = defaultdict(lambda: ZERO)
        for user_id, issued_count in issued_count_by_user.items():
            full_steps = int(issued_count // Decimal(self.settings.wb_issue_bonus_step))
            issued_bonus_by_user[user_id] = Decimal(full_steps * self.settings.wb_issue_bonus_amount)

        reserve_bonus_by_user = defaultdict(lambda: ZERO)
        for user_id, reserve_count in reserve_count_by_user.items():
            reserve_bonus_by_user[user_id] = Decimal(reserve_count * self.settings.reserve_duty_bonus_rub)

        substitution_bonus_by_user = defaultdict(lambda: ZERO)
        for user_id, substitution_count in substitution_count_by_user.items():
            substitution_bonus_by_user[user_id] = Decimal(substitution_count * self.settings.substitution_bonus_rub)

        results: list[EmployeePayrollBreakdown] = []

        for user in users:
            user_input = normalized_user_inputs.get(user.id)

            base = base_by_user[user.id]
            motivation = motivation_by_user[user.id]
            auto_issued_bonus = issued_bonus_by_user[user.id]
            issued_bonus = user_input.issued_bonus_rub if user_input and user_input.issued_bonus_rub is not None else auto_issued_bonus
            rating_bonus = user_input.rating_bonus_rub if user_input else ZERO

            reserve_bonus = reserve_bonus_by_user[user.id]
            substitution_bonus = substitution_bonus_by_user[user.id]

            stuck_deduction = stuck_deduction_by_user[user.id]
            substitution_deduction = substitution_deduction_by_user[user.id]
            defect_deduction = defect_deduction_by_user[user.id]
            dispute = stuck_deduction + substitution_deduction + defect_deduction

            manager_bonus = manager_bonus_by_user[user.id]
            adjustment = adjustments_by_user[user.id]
            debt_adjustment = user_input.debt_adjustment_rub if user_input else ZERO

            subtotal = (
                base
                + motivation
                + rating_bonus
                + issued_bonus
                + reserve_bonus
                + substitution_bonus
                - dispute
                + manager_bonus
                + adjustment
            )
            subtotal = self._money_round(subtotal)

            total = self._money_round(subtotal + debt_adjustment)

            details = {
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "shifts_count": shifts_count_by_user[user.id],
                "hours_total": str(self._money_round(shift_hours_by_user[user.id])),
                "issued_items": str(self._money_round(issued_count_by_user[user.id])),
                "issued_bonus_auto_rub": str(self._money_round(auto_issued_bonus)),
                "issued_bonus_rub": str(self._money_round(issued_bonus)),
                "rating_bonus_rub": str(self._money_round(rating_bonus)),
                "reserve_count": reserve_count_by_user[user.id],
                "reserve_bonus_rub": str(self._money_round(reserve_bonus)),
                "substitution_count": substitution_count_by_user[user.id],
                "substitution_bonus_rub": str(self._money_round(substitution_bonus)),
                "stuck_deduction_rub": str(self._money_round(stuck_deduction)),
                "substitution_deduction_rub": str(self._money_round(substitution_deduction)),
                "defect_deduction_rub": str(self._money_round(defect_deduction)),
                "dispute_deduction_rub": str(self._money_round(dispute)),
                "manager_bonus_rub": str(self._money_round(manager_bonus)),
                "adjustments_rub": str(self._money_round(adjustment)),
                "subtotal_amount_rub": str(self._money_round(subtotal)),
                "debt_adjustment_rub": str(self._money_round(debt_adjustment)),
                "total_amount_rub": str(self._money_round(total)),
            }

            result = EmployeePayrollBreakdown(
                user=user,
                shifts_count=shifts_count_by_user[user.id],
                hours_total=self._money_round(shift_hours_by_user[user.id]),
                base_amount_rub=self._money_round(base),
                motivation_amount_rub=self._money_round(motivation),
                rating_bonus_rub=self._money_round(rating_bonus),
                issued_bonus_rub=self._money_round(issued_bonus),
                reserve_bonus_rub=self._money_round(reserve_bonus),
                substitution_bonus_rub=self._money_round(substitution_bonus),
                stuck_deduction_rub=self._money_round(stuck_deduction),
                substitution_deduction_rub=self._money_round(substitution_deduction),
                defect_deduction_rub=self._money_round(defect_deduction),
                dispute_deduction_rub=self._money_round(dispute),
                manager_bonus_rub=self._money_round(manager_bonus),
                adjustments_rub=self._money_round(adjustment),
                subtotal_amount_rub=self._money_round(subtotal),
                debt_adjustment_rub=self._money_round(debt_adjustment),
                total_amount_rub=total,
                issued_items_total=self._money_round(issued_count_by_user[user.id]),
                details=details,
            )
            results.append(result)

        return results

    async def latest_for_user(self, user_id: int) -> PayrollItem | None:
        return await self.payroll_repo.latest_user_item(user_id)

    @staticmethod
    def _is_shift_payable(shift: Shift) -> bool:
        open_ok = shift.open_approval_status == ApprovalStatus.APPROVED
        close_ok = shift.close_approval_status in (None, ApprovalStatus.APPROVED)
        return open_ok and close_ok

    @staticmethod
    def _shift_hours(shift: Shift) -> Decimal:
        mins = shift.duration_minutes or 0
        return Decimal(mins) / Decimal("60")

    def _calc_shift_base(self, shift: Shift, user: User, point) -> Decimal:
        hours = self._shift_hours(shift)
        is_ozon = bool(point and point.brand.value == "ozon")
        shift_rate = Decimal(user.shift_rate_rub or 0)
        hourly_rate = Decimal(user.hourly_rate_rub or 0)

        # Если указана почасовая ставка и смена существенно меньше 8 часов,
        # считаем почасовую оплату; иначе оплата за смену.
        if hourly_rate > 0 and hours > 0 and hours < Decimal("8"):
            return hourly_rate * hours
        if shift_rate > 0:
            return shift_rate
        if is_ozon:
            return Decimal("1900")
        return hourly_rate * hours

    def _distribute_main_record(
        self,
        record,
        shifts_by_day_point,
        user_id_by_last_name,
        motivation_by_user,
        issued_count_by_user,
        tickets_by_user,
    ) -> None:
        user_id = record.user_id or self._match_user_id_from_name(record.manager_name, user_id_by_last_name)
        acceptance = Decimal(record.acceptance_amount_rub or 0)
        issued = Decimal(record.issued_items_count or 0)
        tickets = Decimal(record.tickets_count or 0)

        if user_id:
            motivation_by_user[user_id] += acceptance
            issued_count_by_user[user_id] += issued
            tickets_by_user[user_id] += tickets
            return

        if not record.point_id:
            return

        day_shifts = shifts_by_day_point.get((record.record_date, record.point_id), [])
        if not day_shifts:
            return

        total_minutes = sum(max(s.duration_minutes or 0, 1) for s in day_shifts)
        if total_minutes <= 0:
            return

        for shift in day_shifts:
            share = Decimal(max(shift.duration_minutes or 0, 1)) / Decimal(total_minutes)
            motivation_by_user[shift.user_id] += acceptance * share
            issued_count_by_user[shift.user_id] += issued * share
            tickets_by_user[shift.user_id] += tickets * share

    @staticmethod
    def _match_user_id_from_name(name: str | None, user_id_by_last_name: dict[str, int]) -> int | None:
        if not name:
            return None
        normalized = normalize_text(name)
        if not normalized:
            return None
        first = normalized.split()[0]
        return user_id_by_last_name.get(first)

    @staticmethod
    def _is_appeal_deduction(appeal: Appeal) -> bool:
        status = normalize_text(appeal.status or "")
        if appeal.charge_to_manager:
            return True
        return ("not_appealed" in status) or ("не оспор" in status)

    async def _calc_manager_bonus_for_tenth(
        self,
        period_end: date,
        users_map: dict[int, User],
        user_id_by_last_name: dict[str, int],
    ) -> defaultdict[int, Decimal]:
        bonus_by_user: defaultdict[int, Decimal] = defaultdict(lambda: ZERO)
        month_start, month_end = month_bounds(period_end)
        appeals_result = await self.session.execute(
            select(Appeal).where(
                Appeal.case_date >= month_start,
                Appeal.case_date <= month_end,
            )
        )
        appeals = appeals_result.scalars().all()

        tickets_by_user: defaultdict[int, Decimal] = defaultdict(lambda: ZERO)
        for appeal in appeals:
            user_id = appeal.assigned_manager_employee_id or self._match_user_id_from_name(
                appeal.assigned_manager_raw, user_id_by_last_name
            )
            if not user_id:
                continue
            tickets_by_user[user_id] += Decimal("1")

        for user_id, user in users_map.items():
            if user.manager_bonus_type == 1:
                bonus_by_user[user_id] += Decimal(self.settings.manager_bonus_1)
            elif user.manager_bonus_type == 2:
                bonus_by_user[user_id] += Decimal(self.settings.manager_bonus_2)
            elif user.manager_bonus_type == 3:
                bonus_by_user[user_id] += tickets_by_user[user_id] * Decimal(self.settings.manager_bonus_3_per_ticket)

        return bonus_by_user

    @staticmethod
    def _to_decimal(value: object, *, default: Decimal = ZERO) -> Decimal:
        if value is None:
            return default
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        s = str(value).strip()
        if not s:
            return default
        s = s.replace(",", ".")
        try:
            return Decimal(s)
        except (InvalidOperation, ValueError):
            return default

    def _normalize_user_inputs(
        self,
        user_inputs: Mapping[int | str, PayrollUserInput | Mapping[str, object]] | None,
    ) -> dict[int, PayrollUserInput]:
        normalized: dict[int, PayrollUserInput] = {}
        if not user_inputs:
            return normalized

        for raw_user_id, raw_input in user_inputs.items():
            try:
                user_id = int(raw_user_id)
            except (TypeError, ValueError):
                continue

            if isinstance(raw_input, PayrollUserInput):
                normalized[user_id] = raw_input
                continue

            if not isinstance(raw_input, Mapping):
                continue

            issued_raw = raw_input.get("issued_bonus_rub")
            issued_value = None
            if issued_raw is not None and str(issued_raw).strip() != "":
                issued_value = self._to_decimal(issued_raw, default=ZERO)

            normalized[user_id] = PayrollUserInput(
                issued_bonus_rub=issued_value,
                rating_bonus_rub=self._to_decimal(raw_input.get("rating_bonus_rub"), default=ZERO),
                debt_adjustment_rub=self._to_decimal(raw_input.get("debt_adjustment_rub"), default=ZERO),
            )

        return normalized

    @staticmethod
    def _money_round(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
