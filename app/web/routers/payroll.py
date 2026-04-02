from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import (
    Appeal,
    ApprovalStatus,
    ManualAdjustment,
    PayrollRun,
    PlannedShift,
    Point,
    Shift,
    ShiftState,
    User,
)
from app.db.repositories import PayrollRepo, UserRepo
from app.services.email import EmailService
from app.services.payroll import PayrollService
from app.services.reports import ReportService
from app.utils.parsing import normalize_text
from app.web.deps import get_db, require_manager

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/payroll", tags=["payroll"])


APPEAL_TYPE_LABELS = {
    "stuck": "Зависшие товары",
    "substitution": "Подмена товара",
    "defect": "Брак товара",
    "other": "Другое списание",
}

APPEAL_STATUS_LABELS = {
    "none": "Без статуса",
    "in_progress": "В работе",
    "appealed": "Оспорено",
    "not_appealed": "Не оспорено",
    "closed": "Закрыто",
}


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _appeal_type_key(raw_value: str | None) -> str:
    normalized = normalize_text(raw_value or "")
    if "stuck" in normalized or "завис" in normalized:
        return "stuck"
    if "substitution" in normalized or "подмен" in normalized:
        return "substitution"
    if "defect" in normalized or "брак" in normalized:
        return "defect"
    return "other"


def _appeal_short_description(appeal: Appeal) -> str:
    for text in (
        appeal.result_comment,
        appeal.charge_comment,
        appeal.non_appeal_reason,
        appeal.feedback_from_nadezhda,
        appeal.feedback_from_anna,
    ):
        if text and text.strip():
            return text.strip()
    return ""


async def _build_employee_sheet_data(
    db: AsyncSession,
    run: PayrollRun,
    item,
    employee: User | None,
    settings,
) -> dict:
    details: dict = {}
    if item.details_json:
        try:
            details = json.loads(item.details_json)
        except Exception:
            details = {}

    points_result = await db.execute(select(Point))
    points_map = {p.id: p for p in points_result.scalars().all()}

    shift_rows: list[dict] = []
    shift_amount_total = Decimal("0.00")
    reserve_rows: list[dict] = []
    substitution_rows: list[dict] = []
    substitution_unpaid_rows: list[dict] = []
    appeal_rows: list[dict] = []
    adjustment_rows: list[dict] = []

    appeal_totals = {
        "stuck": Decimal("0.00"),
        "substitution": Decimal("0.00"),
        "defect": Decimal("0.00"),
        "other": Decimal("0.00"),
    }

    if employee:
        service = PayrollService(db, settings)

        planned_result = await db.execute(
            select(PlannedShift)
            .where(
                PlannedShift.user_id == employee.id,
                PlannedShift.shift_date >= run.period_start,
                PlannedShift.shift_date <= run.period_end,
            )
            .order_by(PlannedShift.shift_date, PlannedShift.id)
        )
        planned_shifts = planned_result.scalars().all()
        substitution_plan_keys: set[tuple[date, int]] = set()
        paid_substitution_keys: set[tuple[date, int]] = set()

        for planned in planned_shifts:
            point = points_map.get(planned.point_id)
            point_name = point.name if point else f"ПВЗ #{planned.point_id}"
            if planned.is_reserve:
                reserve_rows.append({
                    "shift_date": planned.shift_date,
                    "point_name": point_name,
                    "amount_rub": Decimal(settings.reserve_duty_bonus_rub),
                })
            if planned.is_substitution:
                substitution_plan_keys.add((planned.shift_date, planned.point_id))

        shifts_result = await db.execute(
            select(Shift)
            .where(
                Shift.user_id == employee.id,
                Shift.state == ShiftState.CLOSED,
                Shift.shift_date >= run.period_start,
                Shift.shift_date <= run.period_end,
                Shift.open_approval_status == ApprovalStatus.APPROVED,
                or_(Shift.close_approval_status.is_(None), Shift.close_approval_status == ApprovalStatus.APPROVED),
            )
            .order_by(Shift.shift_date, Shift.opened_at)
        )
        shifts = shifts_result.scalars().all()

        shift_rate = _to_decimal(employee.shift_rate_rub)
        hourly_rate = _to_decimal(employee.hourly_rate_rub)

        for shift in shifts:
            point = points_map.get(shift.point_id)
            point_name = point.name if point else f"ПВЗ #{shift.point_id}"
            hours = (Decimal(shift.duration_minutes or 0) / Decimal("60")).quantize(Decimal("0.01"))
            is_ozon = bool(point and point.brand.value == "ozon")

            if hourly_rate > 0 and hours > 0 and hours < Decimal("8"):
                basis = "Почасовая часть"
                rate = hourly_rate
                formula = f"{hourly_rate:.2f} ₽ × {hours:.2f} ч"
            elif shift_rate > 0:
                basis = "Ставка за смену"
                rate = shift_rate
                formula = f"{shift_rate:.2f} ₽ за смену"
            elif is_ozon:
                basis = "Фикс OZON"
                rate = Decimal("1900.00")
                formula = "1900.00 ₽ за смену"
            else:
                basis = "Почасовая часть"
                rate = hourly_rate
                formula = f"{hourly_rate:.2f} ₽ × {hours:.2f} ч"

            amount = service._money_round(service._calc_shift_base(shift, employee, point))
            shift_amount_total += amount

            is_substitution = (shift.shift_date, shift.point_id) in substitution_plan_keys
            if is_substitution:
                paid_substitution_keys.add((shift.shift_date, shift.point_id))
                substitution_rows.append({
                    "shift_date": shift.shift_date,
                    "point_name": point_name,
                    "amount_rub": Decimal(settings.substitution_bonus_rub),
                })

            shift_rows.append({
                "shift_date": shift.shift_date,
                "point_name": point_name,
                "hours": hours,
                "basis": basis,
                "rate_rub": rate,
                "formula": formula,
                "amount_rub": amount,
                "is_substitution": is_substitution,
            })

        for shift_date, point_id in sorted(substitution_plan_keys):
            if (shift_date, point_id) in paid_substitution_keys:
                continue
            point = points_map.get(point_id)
            point_name = point.name if point else f"ПВЗ #{point_id}"
            substitution_unpaid_rows.append({
                "shift_date": shift_date,
                "point_name": point_name,
            })

        user_id_by_last_name: dict[str, int] = {}
        if employee.last_name:
            user_id_by_last_name[normalize_text(employee.last_name)] = employee.id

        appeals_result = await db.execute(
            select(Appeal)
            .where(
                Appeal.case_date >= run.period_start,
                Appeal.case_date <= run.period_end,
            )
            .order_by(Appeal.case_date, Appeal.id)
        )
        appeals = appeals_result.scalars().all()

        for appeal in appeals:
            matched_user_id = appeal.assigned_manager_employee_id or PayrollService._match_user_id_from_name(
                appeal.assigned_manager_raw,
                user_id_by_last_name,
            )
            if matched_user_id != employee.id:
                continue
            if not PayrollService._is_appeal_deduction(appeal):
                continue

            amount = abs(_to_decimal(appeal.amount))
            if amount <= 0:
                continue

            type_key = _appeal_type_key(appeal.appeal_type)
            appeal_totals[type_key] += amount

            point = points_map.get(appeal.point_id)
            point_name = point.name if point else f"ПВЗ #{appeal.point_id}"
            status_label = APPEAL_STATUS_LABELS.get(appeal.status, appeal.status)

            appeal_rows.append({
                "id": appeal.id,
                "case_date": appeal.case_date,
                "point_name": point_name,
                "type_key": type_key,
                "type_label": APPEAL_TYPE_LABELS.get(type_key, APPEAL_TYPE_LABELS["other"]),
                "amount_rub": amount,
                "barcode": appeal.barcode or "",
                "ticket_number": appeal.ticket_number or "",
                "status_label": status_label,
                "description": _appeal_short_description(appeal),
            })

        adjustments_result = await db.execute(
            select(ManualAdjustment)
            .where(
                ManualAdjustment.user_id == employee.id,
                ManualAdjustment.period_start == run.period_start,
                ManualAdjustment.period_end == run.period_end,
            )
            .order_by(ManualAdjustment.id)
        )
        for adj in adjustments_result.scalars().all():
            adjustment_rows.append({
                "amount_rub": adj.amount_rub,
                "adjustment_type": adj.adjustment_type.value,
                "comment": adj.comment or "",
                "created_at": adj.created_at,
            })

    reserve_amount_total = sum((r["amount_rub"] for r in reserve_rows), start=Decimal("0.00"))
    substitution_amount_total = sum((r["amount_rub"] for r in substitution_rows), start=Decimal("0.00"))
    appeal_amount_total = sum(appeal_totals.values(), start=Decimal("0.00"))
    appeal_gap = (Decimal(item.dispute_deduction_rub or 0) - appeal_amount_total).quantize(Decimal("0.01"))
    if abs(appeal_gap) < Decimal("0.01"):
        appeal_gap = Decimal("0.00")

    return {
        "details": details,
        "shift_rows": shift_rows,
        "shift_amount_total": shift_amount_total,
        "reserve_rows": reserve_rows,
        "reserve_amount_total": reserve_amount_total,
        "substitution_rows": substitution_rows,
        "substitution_amount_total": substitution_amount_total,
        "substitution_unpaid_rows": substitution_unpaid_rows,
        "appeal_rows": appeal_rows,
        "appeal_totals": appeal_totals,
        "appeal_gap": appeal_gap,
        "adjustment_rows": adjustment_rows,
    }


def _safe_payout_day(value: object, default: int = 10) -> int:
    try:
        day = int(value)
    except (TypeError, ValueError):
        return default
    return day if day in (10, 25) else default


def _parse_iso_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value or ""))
    except (ValueError, TypeError):
        return None


async def _build_generate_context(
    db: AsyncSession,
    payout_day: int,
    period_start_raw: str,
    period_end_raw: str,
    error: str | None = None,
) -> dict:
    from app.utils.dates import payroll_period_for_payout

    settings = get_settings()
    today = date.today()
    p10_start, p10_end = payroll_period_for_payout(10, today)
    p25_start, p25_end = payroll_period_for_payout(25, today)

    payout_day_selected = _safe_payout_day(payout_day)

    default_start = p10_start.isoformat() if payout_day_selected == 10 else p25_start.isoformat()
    default_end = p10_end.isoformat() if payout_day_selected == 10 else p25_end.isoformat()

    period_start_value = (period_start_raw or default_start).strip()
    period_end_value = (period_end_raw or default_end).strip()

    parsed_start = _parse_iso_date(period_start_value)
    parsed_end = _parse_iso_date(period_end_value)

    preview_rows: list[dict] = []
    preview_error: str | None = None

    if parsed_start and parsed_end:
        if parsed_start > parsed_end:
            preview_error = "Начало периода не может быть позже конца периода"
        else:
            svc = PayrollService(db, settings)
            rows = await svc.preview_payroll(
                period_start=parsed_start,
                period_end=parsed_end,
                payout_day=payout_day_selected,
            )
            rows = sorted(rows, key=lambda r: (r.user.full_name or "").lower())
            for row in rows:
                subtotal_base = (Decimal(row.subtotal_amount_rub) - Decimal(row.issued_bonus_rub)).quantize(Decimal("0.01"))
                preview_rows.append({
                    "user_id": row.user.id,
                    "full_name": row.user.full_name,
                    "speed_bonus_rub": row.motivation_amount_rub,
                    "issued_bonus_auto_rub": row.issued_bonus_rub,
                    "reserve_bonus_rub": row.reserve_bonus_rub,
                    "substitution_bonus_rub": row.substitution_bonus_rub,
                    "stuck_deduction_rub": row.stuck_deduction_rub,
                    "substitution_deduction_rub": row.substitution_deduction_rub,
                    "defect_deduction_rub": row.defect_deduction_rub,
                    "manager_bonus_rub": row.manager_bonus_rub,
                    "adjustments_rub": row.adjustments_rub,
                    "subtotal_base_rub": subtotal_base,
                    "subtotal_amount_rub": row.subtotal_amount_rub,
                    "total_amount_rub": row.total_amount_rub,
                })
    elif period_start_raw or period_end_raw:
        preview_error = "Укажите корректные даты периода"

    return {
        "today": today,
        "p10_start": p10_start.isoformat(),
        "p10_end": p10_end.isoformat(),
        "p25_start": p25_start.isoformat(),
        "p25_end": p25_end.isoformat(),
        "payout_day_selected": payout_day_selected,
        "period_start_value": period_start_value,
        "period_end_value": period_end_value,
        "manager_bonus_3_per_ticket": settings.manager_bonus_3_per_ticket,
        "preview_rows": preview_rows,
        "preview_error": preview_error,
        "error": error,
    }


def _collect_user_inputs_from_form(form) -> dict[str, dict[str, str]]:
    user_inputs: dict[str, dict[str, str]] = {}
    for raw_uid in form.getlist("employee_ids"):
        uid_str = str(raw_uid).strip()
        if not uid_str.isdigit():
            continue

        issued_raw = str(form.get(f"issued_bonus_rub_{uid_str}", "")).strip().replace(",", ".")
        rating_raw = str(form.get(f"rating_bonus_rub_{uid_str}", "")).strip().replace(",", ".")
        debt_raw = str(form.get(f"debt_adjustment_rub_{uid_str}", "")).strip().replace(",", ".")

        user_inputs[uid_str] = {
            "issued_bonus_rub": issued_raw,
            "rating_bonus_rub": rating_raw,
            "debt_adjustment_rub": debt_raw,
        }

    return user_inputs


@router.get("", response_class=HTMLResponse)
async def list_payroll_runs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    repo = PayrollRepo(db)
    runs = await repo.list_runs(limit=50)

    return templates.TemplateResponse(request, "payroll/list.html", {
        "current_user": current_user,
        "active_page": "payroll",
        "runs": runs,
    })


@router.get("/generate", response_class=HTMLResponse)
async def generate_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
    payout_day: int = 10,
    period_start: str = "",
    period_end: str = "",
):
    context = await _build_generate_context(db, payout_day, period_start, period_end)
    context.update({
        "current_user": current_user,
        "active_page": "payroll",
    })
    return templates.TemplateResponse(request, "payroll/generate.html", context)


@router.post("/generate")
async def generate_payroll(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    form = await request.form()
    payout_day = _safe_payout_day(form.get("payout_day", 10))
    period_start_str = str(form.get("period_start", "")).strip()
    period_end_str = str(form.get("period_end", "")).strip()

    period_start = _parse_iso_date(period_start_str)
    period_end = _parse_iso_date(period_end_str)
    if not period_start or not period_end:
        context = await _build_generate_context(
            db,
            payout_day,
            period_start_str,
            period_end_str,
            error="Укажите корректные даты периода",
        )
        context.update({
            "current_user": current_user,
            "active_page": "payroll",
        })
        return templates.TemplateResponse(request, "payroll/generate.html", context)

    user_inputs = _collect_user_inputs_from_form(form)

    settings = get_settings()
    email_svc = EmailService(settings)
    if email_svc.enabled and current_user.email:
        payload = {
            "payout_day": payout_day,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "user_inputs": user_inputs,
        }
        await email_svc.send_confirmation_code(
            db,
            current_user.id,
            current_user.email,
            "payroll_generate",
            json.dumps(payload, ensure_ascii=False),
        )
        return RedirectResponse(url="/confirm/verify?operation=payroll_generate", status_code=302)

    service = PayrollService(db, settings)
    run_id, _ = await service.run_payroll(
        period_start=period_start,
        period_end=period_end,
        payout_day=payout_day,
        generated_by=current_user.id,
        user_inputs=user_inputs,
    )

    return RedirectResponse(url=f"/payroll/{run_id}", status_code=302)


@router.get("/{run_id}", response_class=HTMLResponse)
async def view_payroll_run(
    run_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return RedirectResponse(url="/payroll", status_code=302)

    repo = PayrollRepo(db)
    items = await repo.list_run_items(run_id)

    user_repo = UserRepo(db)
    users = await user_repo.list_all()
    users_map = {u.id: u for u in users}

    total_amount = sum(i.total_amount_rub or 0 for i in items)

    return templates.TemplateResponse(request, "payroll/detail.html", {
        "current_user": current_user,
        "active_page": "payroll",
        "run": run,
        "items": items,
        "users_map": users_map,
        "total_amount": total_amount,
    })


@router.get("/{run_id}/sheet/{item_id}", response_class=HTMLResponse)
async def view_employee_sheet(
    run_id: int,
    item_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
    view: str = "short",
):
    from app.db.models import PayrollItem

    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return RedirectResponse(url="/payroll", status_code=302)

    result = await db.execute(select(PayrollItem).where(PayrollItem.id == item_id, PayrollItem.run_id == run_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url=f"/payroll/{run_id}", status_code=302)

    result = await db.execute(select(User).where(User.id == item.user_id))
    employee = result.scalar_one_or_none()

    view_mode = "full" if view == "full" else "short"
    settings = get_settings()
    details_data = await _build_employee_sheet_data(db=db, run=run, item=item, employee=employee, settings=settings)

    return templates.TemplateResponse(request, "payroll/sheet.html", {
        "current_user": current_user,
        "active_page": "payroll",
        "run": run,
        "item": item,
        "employee": employee,
        "view_mode": view_mode,
        **details_data,
        "manager_bonus_3_per_ticket": settings.manager_bonus_3_per_ticket,
        "reserve_duty_bonus_rub": settings.reserve_duty_bonus_rub,
        "substitution_bonus_rub": settings.substitution_bonus_rub,
    })


@router.get("/{run_id}/sheet/{item_id}/export.xlsx")
async def export_employee_sheet_xlsx(
    run_id: int,
    item_id: int,
    view: str = "short",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    from app.db.models import PayrollItem

    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return RedirectResponse(url="/payroll", status_code=302)

    result = await db.execute(select(PayrollItem).where(PayrollItem.id == item_id, PayrollItem.run_id == run_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url=f"/payroll/{run_id}", status_code=302)

    result = await db.execute(select(User).where(User.id == item.user_id))
    employee = result.scalar_one_or_none()

    settings = get_settings()
    details_data = await _build_employee_sheet_data(db=db, run=run, item=item, employee=employee, settings=settings)
    view_mode = "full" if view == "full" else "short"
    employee_name = employee.full_name if employee else f"Сотрудник #{item.user_id}"

    svc = ReportService(export_dir="/tmp/pvz_exports")
    path = svc.export_employee_sheet_xlsx(
        run_id=run.id,
        item_id=item.id,
        employee_name=employee_name,
        period_start=run.period_start,
        period_end=run.period_end,
        payout_day=run.payout_day,
        item=item,
        view_mode=view_mode,
        details=details_data,
        manager_bonus_3_per_ticket=settings.manager_bonus_3_per_ticket,
        reserve_duty_bonus_rub=settings.reserve_duty_bonus_rub,
        substitution_bonus_rub=settings.substitution_bonus_rub,
    )

    def iterfile():
        with open(path, "rb") as f:
            yield from f

    return StreamingResponse(
        iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get("/{run_id}/sheet/{item_id}/export.pdf")
async def export_employee_sheet_pdf(
    run_id: int,
    item_id: int,
    view: str = "short",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    from app.db.models import PayrollItem

    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return RedirectResponse(url="/payroll", status_code=302)

    result = await db.execute(select(PayrollItem).where(PayrollItem.id == item_id, PayrollItem.run_id == run_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url=f"/payroll/{run_id}", status_code=302)

    result = await db.execute(select(User).where(User.id == item.user_id))
    employee = result.scalar_one_or_none()

    settings = get_settings()
    details_data = await _build_employee_sheet_data(db=db, run=run, item=item, employee=employee, settings=settings)
    view_mode = "full" if view == "full" else "short"
    employee_name = employee.full_name if employee else f"Сотрудник #{item.user_id}"

    svc = ReportService(export_dir="/tmp/pvz_exports")
    try:
        path = svc.export_employee_sheet_pdf(
            run_id=run.id,
            item_id=item.id,
            employee_name=employee_name,
            period_start=run.period_start,
            period_end=run.period_end,
            payout_day=run.payout_day,
            item=item,
            view_mode=view_mode,
            details=details_data,
            manager_bonus_3_per_ticket=settings.manager_bonus_3_per_ticket,
            reserve_duty_bonus_rub=settings.reserve_duty_bonus_rub,
            substitution_bonus_rub=settings.substitution_bonus_rub,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    def iterfile():
        with open(path, "rb") as f:
            yield from f

    return StreamingResponse(
        iterfile(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get("/{run_id}/export")
async def export_payroll_xlsx(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return RedirectResponse(url="/payroll", status_code=302)

    repo = PayrollRepo(db)
    items = await repo.list_run_items(run_id)

    user_repo = UserRepo(db)
    users = await user_repo.list_all()
    users_map = {u.id: u for u in users}

    from app.services.payroll import EmployeePayrollBreakdown

    breakdowns = []
    for item in items:
        user = users_map.get(item.user_id)
        if not user:
            continue

        subtotal = Decimal(item.total_amount_rub or 0) - Decimal(item.debt_adjustment_rub or 0)
        breakdowns.append(EmployeePayrollBreakdown(
            user=user,
            shifts_count=item.shifts_count,
            hours_total=item.hours_total or 0,
            base_amount_rub=item.base_amount_rub or 0,
            motivation_amount_rub=item.motivation_amount_rub or 0,
            rating_bonus_rub=item.rating_bonus_rub or 0,
            issued_bonus_rub=item.issued_bonus_rub or 0,
            reserve_bonus_rub=item.reserve_bonus_rub or 0,
            substitution_bonus_rub=item.substitution_bonus_rub or 0,
            stuck_deduction_rub=item.stuck_deduction_rub or 0,
            substitution_deduction_rub=item.substitution_deduction_rub or 0,
            defect_deduction_rub=item.defect_deduction_rub or 0,
            dispute_deduction_rub=item.dispute_deduction_rub or 0,
            manager_bonus_rub=item.manager_bonus_rub or 0,
            adjustments_rub=item.adjustments_rub or 0,
            subtotal_amount_rub=subtotal,
            debt_adjustment_rub=item.debt_adjustment_rub or 0,
            total_amount_rub=item.total_amount_rub or 0,
            issued_items_total=0,
            details={},
        ))

    svc = ReportService(export_dir="/tmp/pvz_exports")
    path = svc.export_payroll_summary_xlsx(run.period_start, run.period_end, breakdowns)

    def iterfile():
        with open(path, "rb") as f:
            yield from f

    filename = f"payroll_{run.period_start}_{run.period_end}.xlsx"
    return StreamingResponse(
        iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{run_id}/export-sheets")
async def export_employee_sheets_xlsx(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return RedirectResponse(url="/payroll", status_code=302)

    repo = PayrollRepo(db)
    items = await repo.list_run_items(run_id)

    user_repo = UserRepo(db)
    users = await user_repo.list_all()
    users_map = {u.id: u for u in users}

    from app.services.payroll import EmployeePayrollBreakdown

    breakdowns = []
    for item in items:
        user = users_map.get(item.user_id)
        if not user:
            continue

        subtotal = Decimal(item.total_amount_rub or 0) - Decimal(item.debt_adjustment_rub or 0)
        breakdowns.append(EmployeePayrollBreakdown(
            user=user,
            shifts_count=item.shifts_count,
            hours_total=item.hours_total or 0,
            base_amount_rub=item.base_amount_rub or 0,
            motivation_amount_rub=item.motivation_amount_rub or 0,
            rating_bonus_rub=item.rating_bonus_rub or 0,
            issued_bonus_rub=item.issued_bonus_rub or 0,
            reserve_bonus_rub=item.reserve_bonus_rub or 0,
            substitution_bonus_rub=item.substitution_bonus_rub or 0,
            stuck_deduction_rub=item.stuck_deduction_rub or 0,
            substitution_deduction_rub=item.substitution_deduction_rub or 0,
            defect_deduction_rub=item.defect_deduction_rub or 0,
            dispute_deduction_rub=item.dispute_deduction_rub or 0,
            manager_bonus_rub=item.manager_bonus_rub or 0,
            adjustments_rub=item.adjustments_rub or 0,
            subtotal_amount_rub=subtotal,
            debt_adjustment_rub=item.debt_adjustment_rub or 0,
            total_amount_rub=item.total_amount_rub or 0,
            issued_items_total=0,
            details={},
        ))

    svc = ReportService(export_dir="/tmp/pvz_exports")
    path = svc.export_employee_payroll_sheets(run.period_start, run.period_end, breakdowns)

    def iterfile():
        with open(path, "rb") as f:
            yield from f

    filename = f"payroll_sheets_{run.period_start}_{run.period_end}.xlsx"
    return StreamingResponse(
        iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
