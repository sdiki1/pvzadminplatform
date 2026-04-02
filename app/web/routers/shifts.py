from __future__ import annotations

from datetime import date, time
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmployeePointAssignment, PlannedShift, Point, Shift, User, WebUser
from app.utils.parsing import parse_date
from app.web.deps import get_current_user, get_db, is_restricted_manager

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/shifts", tags=["shifts"])


MANAGER_ROLES = {"superadmin", "admin", "senior"}


def _can_manage_all_schedule(current_user: WebUser) -> bool:
    return bool(set(current_user.roles).intersection(MANAGER_ROLES))


def _can_manage_own_schedule(current_user: WebUser) -> bool:
    # managers and employees with a linked employee account can edit their own schedule
    return bool(current_user.user_id and set(current_user.roles).intersection({"employee", "manager"}))


def _can_manage_user_schedule(current_user: WebUser, user_id: int) -> bool:
    if _can_manage_all_schedule(current_user):
        return True
    return bool(_can_manage_own_schedule(current_user) and current_user.user_id == user_id)


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "да"}
    return False


def _parse_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


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


def _parse_time_range(start_raw, end_raw) -> tuple[time | None, time | None, str | None]:
    start_text = str(start_raw or "").strip()
    end_text = str(end_raw or "").strip()
    start_time = _parse_time_value(start_text)
    end_time = _parse_time_value(end_text)
    if (start_text and not start_time) or (end_text and not end_time):
        return None, None, "invalid_time"
    if bool(start_time) != bool(end_time):
        return None, None, "time_range_required"
    if start_time and end_time and end_time <= start_time:
        return None, None, "time_range_invalid"
    return start_time, end_time, None


def _time_hhmm(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value else None


@router.get("", response_class=HTMLResponse)
async def list_shifts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    point_id: int = 0,
    employee_id: int = 0,
    date_from: str = "",
    date_to: str = "",
    show_reserve: int = 0,
    page: int = 1,
    notice: str = "",
    error: str = "",
):
    can_manage_all = _can_manage_all_schedule(current_user)
    can_manage_own = _can_manage_own_schedule(current_user)
    can_manage_schedule = can_manage_all or can_manage_own
    managed_user_id = current_user.user_id if can_manage_own else 0

    effective_employee_id = employee_id
    if can_manage_own and not can_manage_all:
        effective_employee_id = managed_user_id

    per_page = 30
    query = select(Shift)
    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if point_id:
        query = query.where(Shift.point_id == point_id)
    if effective_employee_id:
        query = query.where(Shift.user_id == effective_employee_id)
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
    users_all = users_result.scalars().all()
    users_map = {u.id: u for u in users_all}
    users_active = [u for u in users_all if u.is_active]
    users_filter = users_active
    if can_manage_own and not can_manage_all and managed_user_id:
        users_filter = [u for u in users_active if u.id == managed_user_id]

    editable_users: list[User] = []
    if can_manage_all:
        editable_users = sorted(users_active, key=lambda u: (u.full_name or "").lower())
    elif can_manage_own and managed_user_id:
        own_user = users_map.get(managed_user_id)
        editable_users = [own_user] if own_user else []

    editable_points = points
    if can_manage_own and managed_user_id and not can_manage_all:
        assignment_rows = (await db.execute(
            select(EmployeePointAssignment).where(
                EmployeePointAssignment.user_id == managed_user_id,
                EmployeePointAssignment.is_active == True,
            )
        )).scalars().all()
        allowed_point_ids = {a.point_id for a in assignment_rows}
        editable_points = [p for p in points if p.id in allowed_point_ids]

    planned_query = select(PlannedShift)
    if point_id:
        planned_query = planned_query.where(PlannedShift.point_id == point_id)
    if effective_employee_id:
        planned_query = planned_query.where(PlannedShift.user_id == effective_employee_id)
    if parsed_date_from:
        planned_query = planned_query.where(PlannedShift.shift_date >= parsed_date_from)
    if parsed_date_to:
        planned_query = planned_query.where(PlannedShift.shift_date <= parsed_date_to)
    if show_reserve:
        planned_query = planned_query.where(PlannedShift.is_reserve == True)
    planned_query = planned_query.order_by(
        PlannedShift.shift_date.desc(),
        PlannedShift.start_time.asc(),
        PlannedShift.id.desc(),
    ).limit(500)
    planned_items = (await db.execute(planned_query)).scalars().all()

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
        "employee_id": effective_employee_id,
        "date_from": date_from,
        "date_to": date_to,
        "show_reserve": bool(show_reserve),
        "users_active": users_active,
        "users_filter": users_filter,
        "planned_items": planned_items,
        "editable_users": editable_users,
        "editable_points": editable_points,
        "can_manage_schedule": can_manage_schedule,
        "can_manage_all_schedule": can_manage_all,
        "managed_user_id": managed_user_id,
        "notice": notice,
        "error": error,
        "today_iso": date.today().isoformat(),
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
        "reserve_mode": False,
    })


@router.get("/reserve", response_class=HTMLResponse)
async def reserve_calendar(
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
        "reserve_mode": True,
    })


@router.get("/api/events")
async def shift_events(
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    start: str = "",
    end: str = "",
    point_id: int = 0,
    only_reserve: int = 0,
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
    reserve_mode = bool(only_reserve)

    # --- Actual shifts ---
    shifts: list[Shift] = []
    if not reserve_mode:
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
    if reserve_mode:
        pq = pq.where(PlannedShift.is_reserve == True)

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
                "shift_id": s.id,
                "user_id": s.user_id,
                "point_id": s.point_id,
                "state": state_val,
                "duration_minutes": s.duration_minutes,
                "opened_at": s.opened_at.strftime("%H:%M") if s.opened_at else None,
                "closed_at": s.closed_at.strftime("%H:%M") if s.closed_at else None,
                "notes": s.notes or "",
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
        time_range = None
        if p.start_time and p.end_time:
            time_range = f"{p.start_time.strftime('%H:%M')}-{p.end_time.strftime('%H:%M')}"
            title_parts.append(time_range)
        if p.is_reserve:
            title_parts.append("РЕЗЕРВ")
        if p.is_substitution:
            title_parts.append("РЕЗ.ВЫХОД")
        # Planned: use user color with amber tint if no personal color
        planned_color = (user.color if user and getattr(user, "color", None) else "#f59e0b")
        start_value = str(p.shift_date)
        end_value = None
        if p.start_time and p.end_time:
            start_value = f"{p.shift_date.isoformat()}T{p.start_time.isoformat(timespec='minutes')}"
            end_value = f"{p.shift_date.isoformat()}T{p.end_time.isoformat(timespec='minutes')}"
        events.append({
            "id": f"planned-{p.id}",
            "title": "📅 " + " · ".join(title_parts),
            "start": start_value,
            "end": end_value,
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
                "start_time": _time_hhmm(p.start_time),
                "end_time": _time_hhmm(p.end_time),
                "time_range": time_range or "",
            },
        })

    return JSONResponse(events)


@router.post("/api/planned")
async def create_planned_shift(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    can_manage_all = _can_manage_all_schedule(current_user)
    can_manage_own = _can_manage_own_schedule(current_user)
    if not (can_manage_all or can_manage_own):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    data = await request.json()
    try:
        shift_date = date.fromisoformat(str(data.get("shift_date", ""))[:10])
    except (ValueError, TypeError):
        return JSONResponse({"error": "invalid date"}, status_code=400)

    requested_user_id = _parse_int(data.get("user_id", 0), default=0)
    user_id = requested_user_id if can_manage_all else int(current_user.user_id or 0)
    point_id = _parse_int(data.get("point_id", 0), default=0)
    start_time, end_time, time_error = _parse_time_range(
        data.get("start_time", ""),
        data.get("end_time", ""),
    )
    notes = str(data.get("notes", "")).strip() or None
    is_reserve = _to_bool(data.get("is_reserve", False))
    is_substitution = _to_bool(data.get("is_substitution", False))

    if not user_id or not point_id:
        return JSONResponse({"error": "user_id and point_id required"}, status_code=400)
    if time_error:
        return JSONResponse({"error": time_error}, status_code=400)
    if not _can_manage_user_schedule(current_user, user_id):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    if can_manage_own and not can_manage_all:
        assignment = (await db.execute(
            select(EmployeePointAssignment).where(
                EmployeePointAssignment.user_id == user_id,
                EmployeePointAssignment.point_id == point_id,
                EmployeePointAssignment.is_active == True,
            )
        )).scalar_one_or_none()
        if not assignment:
            return JSONResponse({"error": "point is not assigned to employee"}, status_code=400)

    # Upsert: delete existing for same user+date, then insert
    existing = (await db.execute(
        select(PlannedShift).where(
            PlannedShift.user_id == user_id,
            PlannedShift.shift_date == shift_date,
        )
    )).scalar_one_or_none()

    if existing:
        existing.point_id = point_id
        existing.start_time = start_time
        existing.end_time = end_time
        existing.notes = notes
        existing.is_reserve = is_reserve
        existing.is_substitution = is_substitution
    else:
        ps = PlannedShift(
            user_id=user_id,
            point_id=point_id,
            shift_date=shift_date,
            start_time=start_time,
            end_time=end_time,
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
    if ps and _can_manage_user_schedule(current_user, ps.user_id):
        await db.delete(ps)
        await db.commit()
    return JSONResponse({"ok": True})


@router.post("/planned/create")
async def create_planned_shift_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    can_manage_all = _can_manage_all_schedule(current_user)
    can_manage_own = _can_manage_own_schedule(current_user)
    if not (can_manage_all or can_manage_own):
        return RedirectResponse(url="/shifts?error=forbidden", status_code=302)

    form = await request.form()
    try:
        shift_date = date.fromisoformat(str(form.get("shift_date", ""))[:10])
    except Exception:
        return RedirectResponse(url="/shifts?error=invalid_date", status_code=302)

    requested_user_id = _parse_int(form.get("user_id", 0), default=0)
    user_id = requested_user_id if can_manage_all else int(current_user.user_id or 0)
    point_id = _parse_int(form.get("point_id", 0), default=0)
    start_time, end_time, time_error = _parse_time_range(
        form.get("start_time", ""),
        form.get("end_time", ""),
    )
    notes = str(form.get("notes", "")).strip() or None
    is_reserve = form.get("is_reserve") == "on"
    is_substitution = form.get("is_substitution") == "on"

    if not user_id or not point_id:
        return RedirectResponse(url="/shifts?error=required_fields", status_code=302)
    if time_error:
        return RedirectResponse(url=f"/shifts?error={time_error}", status_code=302)
    if not _can_manage_user_schedule(current_user, user_id):
        return RedirectResponse(url="/shifts?error=forbidden", status_code=302)

    if can_manage_own and not can_manage_all:
        assignment = (await db.execute(
            select(EmployeePointAssignment).where(
                EmployeePointAssignment.user_id == user_id,
                EmployeePointAssignment.point_id == point_id,
                EmployeePointAssignment.is_active == True,
            )
        )).scalar_one_or_none()
        if not assignment:
            return RedirectResponse(url="/shifts?error=point_not_assigned", status_code=302)

    existing = (await db.execute(
        select(PlannedShift).where(
            PlannedShift.user_id == user_id,
            PlannedShift.shift_date == shift_date,
        )
    )).scalar_one_or_none()

    if existing:
        existing.point_id = point_id
        existing.start_time = start_time
        existing.end_time = end_time
        existing.notes = notes
        existing.is_reserve = is_reserve
        existing.is_substitution = is_substitution
    else:
        db.add(PlannedShift(
            user_id=user_id,
            point_id=point_id,
            shift_date=shift_date,
            start_time=start_time,
            end_time=end_time,
            notes=notes,
            is_reserve=is_reserve,
            is_substitution=is_substitution,
        ))
    await db.commit()
    return RedirectResponse(url="/shifts?notice=planned_saved", status_code=302)


@router.post("/planned/{planned_id}/update")
async def update_planned_shift_form(
    planned_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    can_manage_all = _can_manage_all_schedule(current_user)
    can_manage_own = _can_manage_own_schedule(current_user)
    if not (can_manage_all or can_manage_own):
        return RedirectResponse(url="/shifts?error=forbidden", status_code=302)

    planned = (await db.execute(
        select(PlannedShift).where(PlannedShift.id == planned_id)
    )).scalar_one_or_none()
    if not planned:
        return RedirectResponse(url="/shifts?error=not_found", status_code=302)
    if not _can_manage_user_schedule(current_user, planned.user_id):
        return RedirectResponse(url="/shifts?error=forbidden", status_code=302)

    form = await request.form()
    try:
        shift_date = date.fromisoformat(str(form.get("shift_date", ""))[:10])
    except Exception:
        return RedirectResponse(url="/shifts?error=invalid_date", status_code=302)

    new_user_id = _parse_int(form.get("user_id", planned.user_id), default=planned.user_id)
    user_id = new_user_id if can_manage_all else planned.user_id
    point_id = _parse_int(form.get("point_id", planned.point_id), default=planned.point_id)
    start_time, end_time, time_error = _parse_time_range(
        form.get("start_time", ""),
        form.get("end_time", ""),
    )
    notes = str(form.get("notes", "")).strip() or None
    is_reserve = form.get("is_reserve") == "on"
    is_substitution = form.get("is_substitution") == "on"

    if not _can_manage_user_schedule(current_user, user_id):
        return RedirectResponse(url="/shifts?error=forbidden", status_code=302)
    if time_error:
        return RedirectResponse(url=f"/shifts?error={time_error}", status_code=302)

    if can_manage_own and not can_manage_all:
        assignment = (await db.execute(
            select(EmployeePointAssignment).where(
                EmployeePointAssignment.user_id == user_id,
                EmployeePointAssignment.point_id == point_id,
                EmployeePointAssignment.is_active == True,
            )
        )).scalar_one_or_none()
        if not assignment:
            return RedirectResponse(url="/shifts?error=point_not_assigned", status_code=302)

    duplicate = (await db.execute(
        select(PlannedShift).where(
            PlannedShift.user_id == user_id,
            PlannedShift.shift_date == shift_date,
            PlannedShift.id != planned_id,
        )
    )).scalar_one_or_none()

    target = duplicate or planned
    target.user_id = user_id
    target.point_id = point_id
    target.shift_date = shift_date
    target.start_time = start_time
    target.end_time = end_time
    target.notes = notes
    target.is_reserve = is_reserve
    target.is_substitution = is_substitution
    if duplicate:
        await db.delete(planned)

    await db.commit()
    return RedirectResponse(url="/shifts?notice=planned_saved", status_code=302)


@router.post("/planned/{planned_id}/delete")
async def delete_planned_shift_form(
    planned_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    planned = (await db.execute(
        select(PlannedShift).where(PlannedShift.id == planned_id)
    )).scalar_one_or_none()
    if not planned:
        return RedirectResponse(url="/shifts?error=not_found", status_code=302)
    if not _can_manage_user_schedule(current_user, planned.user_id):
        return RedirectResponse(url="/shifts?error=forbidden", status_code=302)

    await db.delete(planned)
    await db.commit()
    return RedirectResponse(url="/shifts?notice=planned_deleted", status_code=302)


@router.get("/api/shift/{shift_id}")
async def get_shift_api(
    shift_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    shift = (await db.execute(select(Shift).where(Shift.id == shift_id))).scalar_one_or_none()
    if not shift:
        return JSONResponse({"error": "not_found"}, status_code=404)

    points_map = {p.id: p for p in (await db.execute(select(Point))).scalars().all()}
    users_map = {u.id: u for u in (await db.execute(select(User))).scalars().all()}
    point = points_map.get(shift.point_id)
    user = users_map.get(shift.user_id)

    state_val = shift.state.value if hasattr(shift.state, "value") else str(shift.state)

    return JSONResponse({
        "id": shift.id,
        "user_id": shift.user_id,
        "point_id": shift.point_id,
        "shift_date": shift.shift_date.isoformat(),
        "state": state_val,
        "opened_at": shift.opened_at.strftime("%H:%M") if shift.opened_at else "",
        "opened_at_full": shift.opened_at.isoformat() if shift.opened_at else "",
        "closed_at": shift.closed_at.strftime("%H:%M") if shift.closed_at else "",
        "closed_at_full": shift.closed_at.isoformat() if shift.closed_at else "",
        "duration_minutes": shift.duration_minutes,
        "notes": shift.notes or "",
        "point_name": point.name if point else "",
        "employee_name": user.full_name if user else "",
    })


@router.post("/api/shift/{shift_id}/edit")
async def edit_shift_api(
    shift_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    if not _can_manage_all_schedule(current_user):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    shift = (await db.execute(select(Shift).where(Shift.id == shift_id))).scalar_one_or_none()
    if not shift:
        return JSONResponse({"error": "not_found"}, status_code=404)

    data = await request.json()

    # point
    new_point_id = _parse_int(data.get("point_id"), 0)
    if new_point_id:
        shift.point_id = new_point_id

    # date
    try:
        new_date = date.fromisoformat(str(data.get("shift_date", ""))[:10])
        shift.shift_date = new_date
    except (ValueError, TypeError):
        pass

    # open time (HH:MM — merge into existing date)
    open_hhmm = str(data.get("opened_at", "")).strip()
    if open_hhmm and ":" in open_hhmm:
        try:
            h, m = map(int, open_hhmm.split(":"))
            shift.opened_at = shift.opened_at.replace(hour=h, minute=m, second=0, microsecond=0)
        except (ValueError, AttributeError):
            pass

    # close time
    close_hhmm = str(data.get("closed_at", "")).strip()
    from datetime import datetime as dt
    if close_hhmm and ":" in close_hhmm:
        try:
            h, m = map(int, close_hhmm.split(":"))
            if shift.closed_at:
                shift.closed_at = shift.closed_at.replace(hour=h, minute=m, second=0, microsecond=0)
            else:
                # create closed_at on same date as opened_at
                shift.closed_at = shift.opened_at.replace(hour=h, minute=m, second=0, microsecond=0)
        except (ValueError, AttributeError):
            pass
    elif close_hhmm == "":
        shift.closed_at = None

    # state
    new_state = str(data.get("state", "")).strip()
    if new_state in ("open", "closed"):
        from app.db.models import ShiftState
        shift.state = ShiftState.OPEN if new_state == "open" else ShiftState.CLOSED

    # recalc duration if both timestamps present
    if shift.opened_at and shift.closed_at:
        diff = (shift.closed_at - shift.opened_at).total_seconds()
        shift.duration_minutes = max(0, int(diff / 60))
    elif new_state == "open":
        shift.closed_at = None
        shift.duration_minutes = None

    # notes
    if "notes" in data:
        shift.notes = str(data["notes"]).strip() or None

    await db.commit()
    return JSONResponse({"ok": True})
