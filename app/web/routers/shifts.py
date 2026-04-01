from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PlannedShift, Point, Shift, User, WebUser
from app.utils.parsing import parse_date
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
    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if point_id:
        query = query.where(Shift.point_id == point_id)
    if employee_id:
        query = query.where(Shift.user_id == employee_id)
    if parsed_date_from:
        query = query.where(Shift.shift_date >= parsed_date_from)
    if parsed_date_to:
        query = query.where(Shift.shift_date <= parsed_date_to)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(Shift.shift_date.desc(), Shift.opened_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    shifts = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    points_result = await db.execute(select(Point))
    points = points_result.scalars().all()
    points_map = {p.id: p for p in points}

    users_result = await db.execute(select(User))
    users_map = {u.id: u for u in users_result.scalars().all()}

    return templates.TemplateResponse(request, "shifts/list.html", {
        "current_user": current_user,
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
        "date_to": date_to,
        "shift_state_labels": {"open": "Открыта", "closed": "Закрыта"},
    })


@router.get("/calendar", response_class=HTMLResponse)
async def shift_calendar(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    points_result = await db.execute(select(Point).where(Point.is_active == True).order_by(Point.name))
    points = points_result.scalars().all()

    users_result = await db.execute(
        select(User).where(User.is_active == True).order_by(User.full_name)
    )
    users = users_result.scalars().all()

    return templates.TemplateResponse(request, "shifts/calendar.html", {
        "current_user": current_user,
        "active_page": "shifts",
        "points": points,
        "users": users,
    })


@router.get("/api/events")
async def shift_events(
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    start: str = "",
    end: str = "",
    point_id: int = 0,
):
    def _parse_date(s: str) -> date | None:
        if not s:
            return None
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None

    d_start = _parse_date(start)
    d_end = _parse_date(end)

    # --- Actual shifts ---
    q = select(Shift)
    if d_start:
        q = q.where(Shift.shift_date >= d_start)
    if d_end:
        q = q.where(Shift.shift_date <= d_end)
    if point_id:
        q = q.where(Shift.point_id == point_id)

    shifts = (await db.execute(q)).scalars().all()

    # --- Planned shifts ---
    pq = select(PlannedShift)
    if d_start:
        pq = pq.where(PlannedShift.shift_date >= d_start)
    if d_end:
        pq = pq.where(PlannedShift.shift_date <= d_end)
    if point_id:
        pq = pq.where(PlannedShift.point_id == point_id)

    planned = (await db.execute(pq)).scalars().all()

    users_map = {u.id: u for u in (await db.execute(select(User))).scalars().all()}
    points_map = {p.id: p for p in (await db.execute(select(Point))).scalars().all()}

    def _user_color(user, state: str) -> str:
        """Use the employee's personal color if set, otherwise fall back to state defaults."""
        if user and getattr(user, "color", None):
            # Darken slightly for closed shifts to show state distinction
            return user.color
        return {"open": "#3b82f6", "closed": "#10b981"}.get(state, "#6b7280")

    events = []

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
        color = _user_color(user, state_val)
        # Closed shifts: add slight transparency via border to distinguish visually
        border_color = color
        opacity_style = "opacity:0.7" if state_val == "closed" else ""
        events.append({
            "id": f"shift-{s.id}",
            "title": " · ".join(title_parts),
            "start": str(s.shift_date),
            "color": color,
            "borderColor": border_color,
            "textColor": "#ffffff",
            "extendedProps": {
                "kind": "actual",
                "user_id": s.user_id,
                "point_id": s.point_id,
                "state": state_val,
                "duration_minutes": s.duration_minutes,
                "point": point.name if point else None,
                "employee": user.full_name if user else None,
                "opacity_style": opacity_style,
            },
        })

    for p in planned:
        user = users_map.get(p.user_id)
        point = points_map.get(p.point_id)
        title_parts = [user.full_name if user else "?"]
        if point:
            title_parts.append(point.short_name or point.name)
        if p.is_reserve:
            title_parts.append("РЕЗЕРВ")
        if p.is_substitution:
            title_parts.append("ПОДМЕНА")
        # Planned: use user color with amber tint if no personal color
        planned_color = (user.color if user and getattr(user, "color", None) else "#f59e0b")
        events.append({
            "id": f"planned-{p.id}",
            "title": "📅 " + " · ".join(title_parts),
            "start": str(p.shift_date),
            "color": planned_color,
            "borderColor": "#d97706",
            "textColor": "#1a1a1a",
            "extendedProps": {
                "kind": "planned",
                "planned_id": p.id,
                "user_id": p.user_id,
                "point_id": p.point_id,
                "is_reserve": bool(p.is_reserve),
                "is_substitution": bool(p.is_substitution),
                "point": point.name if point else None,
                "employee": user.full_name if user else None,
                "notes": p.notes or "",
            },
        })

    return JSONResponse(events)


@router.post("/api/planned")
async def create_planned_shift(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    def _to_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "да"}
        return False

    data = await request.json()
    try:
        shift_date = date.fromisoformat(str(data.get("shift_date", ""))[:10])
    except (ValueError, TypeError):
        return JSONResponse({"error": "invalid date"}, status_code=400)

    user_id = int(data.get("user_id", 0))
    point_id = int(data.get("point_id", 0))
    notes = str(data.get("notes", "")).strip() or None
    is_reserve = _to_bool(data.get("is_reserve", False))
    is_substitution = _to_bool(data.get("is_substitution", False))

    if not user_id or not point_id:
        return JSONResponse({"error": "user_id and point_id required"}, status_code=400)

    # Upsert: delete existing for same user+date, then insert
    existing = (await db.execute(
        select(PlannedShift).where(
            PlannedShift.user_id == user_id,
            PlannedShift.shift_date == shift_date,
        )
    )).scalar_one_or_none()

    if existing:
        existing.point_id = point_id
        existing.notes = notes
        existing.is_reserve = is_reserve
        existing.is_substitution = is_substitution
    else:
        ps = PlannedShift(
            user_id=user_id,
            point_id=point_id,
            shift_date=shift_date,
            is_reserve=is_reserve,
            is_substitution=is_substitution,
            notes=notes,
        )
        db.add(ps)

    await db.commit()
    return JSONResponse({"ok": True})


@router.delete("/api/planned/{planned_id}")
async def delete_planned_shift(
    planned_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    ps = (await db.execute(
        select(PlannedShift).where(PlannedShift.id == planned_id)
    )).scalar_one_or_none()
    if ps:
        await db.delete(ps)
        await db.commit()
    return JSONResponse({"ok": True})
