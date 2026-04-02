from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AdjustmentType,
    ManualAdjustment,
    Point,
    Shift,
    ShiftState,
    TardinessRecord,
    User,
    WebUser,
)
from app.utils.parsing import parse_date
from app.web.deps import get_current_user, get_db, require_manager

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/tardiness", tags=["tardiness"])

TZ = ZoneInfo("Asia/Yekaterinburg")

# Fine thresholds (minutes → RUB)
FINE_TIERS = [
    (10, 30, Decimal("500")),   # 10–30 min → 500 ₽
    (30, 60, Decimal("1000")),  # 30–60 min → 1 000 ₽
    (60, None, Decimal("1000")), # >60 min → 1 000 ₽ (same ceiling)
]


def _calc_fine(delay_minutes: int) -> Decimal:
    for low, high, amount in FINE_TIERS:
        if high is None:
            if delay_minutes >= low:
                return amount
        elif low <= delay_minutes < high:
            return amount
    return Decimal("0")


def _delay_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} мин"
    h, m = divmod(minutes, 60)
    return f"{h}ч {m}мин" if m else f"{h}ч"


@router.get("", response_class=HTMLResponse)
async def list_tardiness(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_manager),
    point_id: int = 0,
    employee_id: int = 0,
    date_from: str = "",
    date_to: str = "",
    excused: str = "",
    page: int = 1,
):
    per_page = 30
    query = select(TardinessRecord)

    if point_id:
        query = query.where(TardinessRecord.point_id == point_id)
    if employee_id:
        query = query.where(TardinessRecord.user_id == employee_id)
    if date_from:
        d = parse_date(date_from)
        if d:
            query = query.where(TardinessRecord.shift_date >= d)
    if date_to:
        d = parse_date(date_to)
        if d:
            query = query.where(TardinessRecord.shift_date <= d)
    if excused == "yes":
        query = query.where(TardinessRecord.is_excused == True)
    elif excused == "no":
        query = query.where(TardinessRecord.is_excused == False)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(TardinessRecord.shift_date.desc(), TardinessRecord.id.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    items = (await db.execute(query)).scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    points = (await db.execute(select(Point).where(Point.is_active == True).order_by(Point.name))).scalars().all()
    employees = (await db.execute(select(User).where(User.is_active == True).order_by(User.full_name))).scalars().all()
    points_map = {p.id: p for p in (await db.execute(select(Point))).scalars().all()}
    users_map = {u.id: u for u in (await db.execute(select(User))).scalars().all()}

    total_fine = sum(i.fine_amount for i in items if not i.is_excused)

    return templates.TemplateResponse(request, "tardiness/list.html", {
        "current_user": current_user,
        "active_page": "tardiness",
        "items": items,
        "total": total,
        "total_fine": total_fine,
        "page": page,
        "total_pages": total_pages,
        "points": points,
        "employees": employees,
        "points_map": points_map,
        "users_map": users_map,
        "point_id": point_id,
        "employee_id": employee_id,
        "date_from": date_from,
        "date_to": date_to,
        "excused": excused,
        "delay_label": _delay_label,
    })


@router.get("/scan", response_class=HTMLResponse)
async def scan_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_manager),
    date_from: str = "",
    date_to: str = "",
):
    """Show how many new tardiness records would be detected without saving."""
    today = date.today()
    d_from = parse_date(date_from) if date_from else today - timedelta(days=7)
    d_to = parse_date(date_to) if date_to else today

    preview = await _detect_tardiness(db, d_from, d_to, dry_run=True)

    return templates.TemplateResponse(request, "tardiness/scan.html", {
        "current_user": current_user,
        "active_page": "tardiness",
        "preview": preview,
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
    })


@router.post("/scan")
async def run_scan(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_manager),
):
    """Actually create TardinessRecord rows for detected tardiness in a date range."""
    form = await request.form()
    d_from = parse_date(form.get("date_from", "")) or (date.today() - timedelta(days=7))
    d_to = parse_date(form.get("date_to", "")) or date.today()

    created = await _detect_tardiness(db, d_from, d_to, dry_run=False, created_by=current_user.id)
    await db.commit()

    return RedirectResponse(url=f"/tardiness?date_from={d_from}&date_to={d_to}", status_code=302)


@router.post("/{record_id}/excuse")
async def excuse_record(
    record_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_manager),
):
    """Mark a tardiness record as excused (waive the fine)."""
    rec = (await db.execute(
        select(TardinessRecord).where(TardinessRecord.id == record_id)
    )).scalar_one_or_none()
    if not rec:
        return RedirectResponse(url="/tardiness", status_code=302)

    form = await request.form()
    rec.is_excused = True
    rec.excuse_comment = str(form.get("comment", "")).strip() or None
    rec.fine_amount = Decimal("0")
    await db.commit()
    return RedirectResponse(url="/tardiness", status_code=302)


@router.post("/{record_id}/charge")
async def charge_record(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_manager),
):
    """Create a ManualAdjustment (deduction) for this tardiness record."""
    rec = (await db.execute(
        select(TardinessRecord).where(TardinessRecord.id == record_id)
    )).scalar_one_or_none()
    if not rec or rec.is_excused or rec.adjustment_id:
        return RedirectResponse(url="/tardiness", status_code=302)

    # Find the period: use shift_date as both period_start and period_end
    adj = ManualAdjustment(
        user_id=rec.user_id,
        period_start=rec.shift_date,
        period_end=rec.shift_date,
        amount_rub=rec.fine_amount,
        adjustment_type=AdjustmentType.DEDUCTION,
        comment=f"Опоздание {_delay_label(rec.delay_minutes)} ({rec.shift_date.strftime('%d.%m.%Y')})",
        created_by=current_user.id,
    )
    db.add(adj)
    await db.flush()
    rec.adjustment_id = adj.id
    await db.commit()
    return RedirectResponse(url="/tardiness", status_code=302)


@router.post("/{record_id}/delete")
async def delete_record(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_manager),
):
    rec = (await db.execute(
        select(TardinessRecord).where(TardinessRecord.id == record_id)
    )).scalar_one_or_none()
    if rec:
        await db.delete(rec)
        await db.commit()
    return RedirectResponse(url="/tardiness", status_code=302)


async def _detect_tardiness(
    db: AsyncSession,
    d_from: date,
    d_to: date,
    dry_run: bool = True,
    created_by: int | None = None,
) -> list[dict]:
    """
    Scan closed/open shifts in [d_from, d_to].
    For each shift where opened_at > point.work_start + 10 min,
    create a TardinessRecord unless one already exists for that shift.
    Returns a list of dicts describing detected records (for preview or after save).
    """
    # Load all points
    points_map = {p.id: p for p in (await db.execute(select(Point))).scalars().all()}
    users_map = {u.id: u for u in (await db.execute(select(User))).scalars().all()}

    # Existing tardiness shift_ids to avoid duplicates
    existing_result = await db.execute(
        select(TardinessRecord.shift_id).where(
            TardinessRecord.shift_date >= d_from,
            TardinessRecord.shift_date <= d_to,
        )
    )
    existing_shift_ids = {row[0] for row in existing_result.all()}

    shifts_result = await db.execute(
        select(Shift).where(
            Shift.shift_date >= d_from,
            Shift.shift_date <= d_to,
        ).order_by(Shift.shift_date, Shift.opened_at)
    )
    shifts = shifts_result.scalars().all()

    detected: list[dict] = []

    for shift in shifts:
        if shift.id in existing_shift_ids:
            continue

        point = points_map.get(shift.point_id)
        if not point or point.work_start is None:
            continue

        # Build planned start datetime in naive local time
        planned_dt = datetime.combine(shift.shift_date, point.work_start)
        actual_dt = shift.opened_at  # already naive (stored without tz)

        delay_seconds = (actual_dt - planned_dt).total_seconds()
        delay_minutes = int(delay_seconds / 60)

        if delay_minutes < 10:
            continue

        fine = _calc_fine(delay_minutes)
        user = users_map.get(shift.user_id)

        entry = {
            "shift_id": shift.id,
            "user_id": shift.user_id,
            "user_name": user.full_name if user else f"#{shift.user_id}",
            "point_id": shift.point_id,
            "point_name": point.name,
            "shift_date": shift.shift_date,
            "planned_start": planned_dt,
            "actual_start": actual_dt,
            "delay_minutes": delay_minutes,
            "fine_amount": fine,
        }
        detected.append(entry)

        if not dry_run:
            rec = TardinessRecord(
                shift_id=shift.id,
                user_id=shift.user_id,
                point_id=shift.point_id,
                shift_date=shift.shift_date,
                planned_start=planned_dt,
                actual_start=actual_dt,
                delay_minutes=delay_minutes,
                fine_amount=fine,
                is_excused=False,
                created_by_user_id=created_by,
            )
            db.add(rec)

    return detected
