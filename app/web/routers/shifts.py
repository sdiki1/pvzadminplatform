from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Point, Shift, User, WebUser
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/shifts", tags=["shifts"])


@router.get("", response_class=HTMLResponse)
async def list_shifts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    point_id: int = 0,
    employee_id: int = 0,
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
):
    per_page = 30
    query = select(Shift)

    if point_id:
        query = query.where(Shift.point_id == point_id)
    if employee_id:
        query = query.where(Shift.user_id == employee_id)
    if date_from:
        query = query.where(Shift.shift_date >= date_from)
    if date_to:
        query = query.where(Shift.shift_date <= date_to)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(Shift.shift_date.desc(), Shift.opened_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    shifts = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Lookups
    points_result = await db.execute(select(Point))
    points = points_result.scalars().all()
    points_map = {p.id: p for p in points}

    users_result = await db.execute(select(User))
    users_map = {u.id: u for u in users_result.scalars().all()}

    return templates.TemplateResponse(request, "shifts/list.html", {"current_user": current_user,
        "active_page": "shifts",
        "items": shifts,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "points": points,
        "points_map": points_map,
        "users_map": users_map,
        "point_id": point_id,
        "employee_id": employee_id,
        "date_from": date_from,
        "date_to": date_to})


@router.get("/calendar", response_class=HTMLResponse)
async def shift_calendar(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()

    return templates.TemplateResponse(request, "shifts/calendar.html", {"current_user": current_user,
        "active_page": "shifts",
        "points": points})


@router.get("/api/events")
async def shift_events(
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    start: str = "",
    end: str = "",
    point_id: int = 0,
):
    query = select(Shift)

    # FullCalendar sends ISO strings like "2025-03-01T00:00:00+03:00" —
    # extract just the date part for comparison with DATE columns
    def _parse_date(s: str) -> date | None:
        if not s:
            return None
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None

    d_start = _parse_date(start)
    d_end = _parse_date(end)
    if d_start:
        query = query.where(Shift.shift_date >= d_start)
    if d_end:
        query = query.where(Shift.shift_date <= d_end)
    if point_id:
        query = query.where(Shift.point_id == point_id)

    result = await db.execute(query)
    shifts = result.scalars().all()

    users_result = await db.execute(select(User))
    users_map = {u.id: u for u in users_result.scalars().all()}

    points_result = await db.execute(select(Point))
    points_map = {p.id: p for p in points_result.scalars().all()}

    events = []
    colors = {"open": "#3b82f6", "closed": "#10b981"}
    for s in shifts:
        user = users_map.get(s.user_id)
        point = points_map.get(s.point_id)
        state_val = s.state.value if hasattr(s.state, "value") else str(s.state)
        duration_h = round(s.duration_minutes / 60, 1) if s.duration_minutes else None
        title_parts = [user.full_name if user else "?"]
        if point:
            title_parts.append(point.short_name or point.name)
        if duration_h:
            title_parts.append(f"{duration_h}ч")
        events.append({
            "id": s.id,
            "title": " · ".join(title_parts),
            "start": str(s.shift_date),
            "color": colors.get(state_val, "#6b7280"),
            "extendedProps": {
                "state": state_val,
                "duration_minutes": s.duration_minutes,
                "point": point.name if point else None,
                "employee": user.full_name if user else None,
            },
        })

    return JSONResponse(events)
