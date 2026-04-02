from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmployeePointAssignment, PlannedShift, Point, Shift, ShiftState, User, WebUser, GeoStatus, ApprovalStatus
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/my", tags=["my"])
TZ = ZoneInfo("Asia/Yekaterinburg")


def _parse_time_value(value) -> time | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 5:
        text = f"{text}:00"
    try:
        return time.fromisoformat(text)
    except ValueError:
        return None


def _parse_time_range(start_raw, end_raw) -> tuple[time | None, time | None, bool]:
    start_text = str(start_raw or "").strip()
    end_text = str(end_raw or "").strip()
    start_time = _parse_time_value(start_text)
    end_time = _parse_time_value(end_text)
    if (start_text and not start_time) or (end_text and not end_time):
        return None, None, False
    if bool(start_time) != bool(end_time):
        return None, None, False
    if start_time and end_time and end_time <= start_time:
        return None, None, False
    return start_time, end_time, True


@router.get("", response_class=HTMLResponse)
async def my_portal(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    if not current_user.user_id:
        return templates.TemplateResponse(request, "my/not_linked.html", {
            "current_user": current_user, "active_page": "my"
        })

    employee = (await db.execute(select(User).where(User.id == current_user.user_id))).scalar_one_or_none()

    # Today's open shift
    today = date.today()
    open_shift = (await db.execute(
        select(Shift).where(
            Shift.user_id == current_user.user_id,
            Shift.state == ShiftState.OPEN,
        )
    )).scalar_one_or_none()

    # Today's shifts
    today_shifts = (await db.execute(
        select(Shift).where(
            Shift.user_id == current_user.user_id,
            Shift.shift_date == today,
        ).order_by(Shift.opened_at.desc())
    )).scalars().all()
    today_closed = [s for s in today_shifts if s.state == ShiftState.CLOSED]

    # Upcoming planned shifts (next 14 days)
    upcoming_planned = (await db.execute(
        select(PlannedShift).where(
            PlannedShift.user_id == current_user.user_id,
            PlannedShift.shift_date >= today,
            PlannedShift.shift_date <= today + timedelta(days=14),
        ).order_by(PlannedShift.shift_date, PlannedShift.start_time.asc(), PlannedShift.id.asc())
    )).scalars().all()

    # Points this employee is assigned to (for shift open dropdown)
    assignments = (await db.execute(
        select(EmployeePointAssignment).where(
            EmployeePointAssignment.user_id == current_user.user_id,
            EmployeePointAssignment.is_active == True,
        )
    )).scalars().all()
    point_ids = [a.point_id for a in assignments]
    if point_ids:
        points = (await db.execute(
            select(Point).where(Point.id.in_(point_ids), Point.is_active == True).order_by(Point.name)
        )).scalars().all()
    else:
        points = (await db.execute(select(Point).where(Point.is_active == True).order_by(Point.name))).scalars().all()

    points_map = {p.id: p for p in (await db.execute(select(Point))).scalars().all()}

    return templates.TemplateResponse(request, "my/index.html", {
        "current_user": current_user,
        "active_page": "my",
        "employee": employee,
        "open_shift": open_shift,
        "today_shifts": today_shifts,
        "today_closed": today_closed,
        "upcoming_planned": upcoming_planned,
        "points": points,
        "points_map": points_map,
        "today": today,
    })


@router.post("/shift/open")
async def open_shift(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    if not current_user.user_id:
        return RedirectResponse(url="/my", status_code=302)

    # Check no open shift already
    open_shift = (await db.execute(
        select(Shift).where(
            Shift.user_id == current_user.user_id,
            Shift.state == ShiftState.OPEN,
        )
    )).scalar_one_or_none()
    if open_shift:
        return RedirectResponse(url="/my", status_code=302)

    form = await request.form()
    point_id = int(form.get("point_id", 0))
    if not point_id:
        return RedirectResponse(url="/my", status_code=302)

    now = datetime.now(TZ).replace(tzinfo=None)
    shift = Shift(
        user_id=current_user.user_id,
        point_id=point_id,
        shift_date=now.date(),
        state=ShiftState.OPEN,
        opened_at=now,
        open_lat=0.0,
        open_lon=0.0,
        open_distance_m=0.0,
        open_geo_status=GeoStatus.OK,
        open_approval_status=ApprovalStatus.APPROVED,
        notes="Открыта через веб-кабинет",
    )
    db.add(shift)
    await db.commit()
    return RedirectResponse(url="/my", status_code=302)


@router.post("/shift/close")
async def close_shift(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    if not current_user.user_id:
        return RedirectResponse(url="/my", status_code=302)

    open_shift = (await db.execute(
        select(Shift).where(
            Shift.user_id == current_user.user_id,
            Shift.state == ShiftState.OPEN,
        )
    )).scalar_one_or_none()
    if not open_shift:
        return RedirectResponse(url="/my", status_code=302)

    now = datetime.now(TZ).replace(tzinfo=None)
    open_shift.closed_at = now
    open_shift.state = ShiftState.CLOSED
    open_shift.close_lat = 0.0
    open_shift.close_lon = 0.0
    open_shift.close_distance_m = 0.0
    open_shift.close_geo_status = GeoStatus.OK
    open_shift.close_approval_status = ApprovalStatus.APPROVED
    duration = int((now - open_shift.opened_at).total_seconds() / 60)
    open_shift.duration_minutes = max(0, duration)
    await db.commit()
    return RedirectResponse(url="/my", status_code=302)


@router.post("/schedule/add")
async def add_planned(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    if not current_user.user_id:
        return RedirectResponse(url="/my", status_code=302)

    form = await request.form()
    try:
        shift_date = date.fromisoformat(str(form.get("shift_date", ""))[:10])
    except (ValueError, TypeError):
        return RedirectResponse(url="/my", status_code=302)
    point_id = int(form.get("point_id", 0))
    if not point_id:
        return RedirectResponse(url="/my", status_code=302)
    start_time, end_time, is_time_range_ok = _parse_time_range(
        form.get("start_time", ""),
        form.get("end_time", ""),
    )
    if not is_time_range_ok:
        return RedirectResponse(url="/my", status_code=302)
    notes = str(form.get("notes", "")).strip() or None

    existing = (await db.execute(
        select(PlannedShift).where(
            PlannedShift.user_id == current_user.user_id,
            PlannedShift.shift_date == shift_date,
        )
    )).scalar_one_or_none()

    if existing:
        existing.point_id = point_id
        existing.start_time = start_time
        existing.end_time = end_time
        existing.notes = notes
    else:
        db.add(PlannedShift(
            user_id=current_user.user_id,
            point_id=point_id,
            shift_date=shift_date,
            start_time=start_time,
            end_time=end_time,
            notes=notes,
            created_at=datetime.now(TZ).replace(tzinfo=None),
        ))
    await db.commit()
    return RedirectResponse(url="/my", status_code=302)


@router.post("/schedule/{planned_id}/delete")
async def delete_planned(
    planned_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    if not current_user.user_id:
        return RedirectResponse(url="/my", status_code=302)

    ps = (await db.execute(
        select(PlannedShift).where(
            PlannedShift.id == planned_id,
            PlannedShift.user_id == current_user.user_id,  # safety: only own
        )
    )).scalar_one_or_none()
    if ps:
        await db.delete(ps)
        await db.commit()
    return RedirectResponse(url="/my", status_code=302)
