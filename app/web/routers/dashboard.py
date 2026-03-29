from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appeal,
    DefectIncident,
    Point,
    Shift,
    SOSIncident,
    SupplyRequestHeader,
    User,
    WebUser,
)
from app.web.deps import get_current_user_optional, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user_optional),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)

    today = date.today()

    # Counts for dashboard cards
    points_count = (await db.execute(select(func.count(Point.id)).where(Point.is_active == True))).scalar() or 0
    employees_count = (await db.execute(select(func.count(User.id)).where(User.is_active == True))).scalar() or 0

    open_sos = (await db.execute(
        select(func.count(SOSIncident.id)).where(SOSIncident.status == "open")
    )).scalar() or 0

    new_defects = (await db.execute(
        select(func.count(DefectIncident.id)).where(DefectIncident.status == "new")
    )).scalar() or 0

    today_shifts = (await db.execute(
        select(func.count(Shift.id)).where(Shift.shift_date == today)
    )).scalar() or 0

    active_supplies = (await db.execute(
        select(func.count(SupplyRequestHeader.id)).where(
            SupplyRequestHeader.status.notin_(["closed", "cancelled"])
        )
    )).scalar() or 0

    open_appeals = (await db.execute(
        select(func.count(Appeal.id)).where(
            Appeal.status.in_(["none", "in_progress"])
        )
    )).scalar() or 0

    # Recent SOS
    recent_sos_result = await db.execute(
        select(SOSIncident)
        .order_by(SOSIncident.created_at.desc())
        .limit(5)
    )
    recent_sos = recent_sos_result.scalars().all()

    # Recent defects
    recent_defects_result = await db.execute(
        select(DefectIncident)
        .order_by(DefectIncident.created_at.desc())
        .limit(5)
    )
    recent_defects = recent_defects_result.scalars().all()

    # Points lookup for display
    points_result = await db.execute(select(Point))
    points_map = {p.id: p for p in points_result.scalars().all()}

    return templates.TemplateResponse("dashboard/index.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "dashboard",
        "points_count": points_count,
        "employees_count": employees_count,
        "open_sos": open_sos,
        "new_defects": new_defects,
        "today_shifts": today_shifts,
        "active_supplies": active_supplies,
        "open_appeals": open_appeals,
        "recent_sos": recent_sos,
        "recent_defects": recent_defects,
        "points_map": points_map,
        "today": today,
    })
