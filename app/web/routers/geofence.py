from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApprovalStatus, GeofenceException, Shift, User, Point
from app.db.repositories import GeofenceExceptionRepo, ShiftRepo
from app.web.deps import get_current_user, get_db, require_manager

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/geofence", tags=["geofence"])


@router.get("", response_class=HTMLResponse)
async def list_geofence_exceptions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
    status: str = "pending",
):
    query = select(GeofenceException)
    if status:
        query = query.where(GeofenceException.status == status)
    query = query.order_by(GeofenceException.created_at.desc()).limit(100)

    result = await db.execute(query)
    items = result.scalars().all()

    shift_ids = [i.shift_id for i in items]
    shifts_result = await db.execute(select(Shift).where(Shift.id.in_(shift_ids))) if shift_ids else None
    shifts_map = {s.id: s for s in (shifts_result.scalars().all() if shifts_result else [])}

    users_result = await db.execute(select(User))
    users_map = {u.id: u for u in users_result.scalars().all()}

    points_result = await db.execute(select(Point))
    points_map = {p.id: p for p in points_result.scalars().all()}

    return templates.TemplateResponse(request, "geofence/list.html", {
        "current_user": current_user,
        "active_page": "geofence",
        "items": items,
        "shifts_map": shifts_map,
        "users_map": users_map,
        "points_map": points_map,
        "status": status,
    })


@router.post("/{exception_id}/approve")
async def approve_exception(
    exception_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    repo = GeofenceExceptionRepo(db)
    ge = await repo.get_by_id(exception_id)
    if not ge:
        return RedirectResponse(url="/geofence", status_code=302)

    await repo.set_status(exception_id, ApprovalStatus.APPROVED, reviewed_by=current_user.id)

    shift_repo = ShiftRepo(db)
    if ge.event == "open":
        await shift_repo.update_open_approval(ge.shift_id, ApprovalStatus.APPROVED)
    elif ge.event == "close":
        await shift_repo.update_close_approval(ge.shift_id, ApprovalStatus.APPROVED)

    return RedirectResponse(url="/geofence", status_code=302)


@router.post("/{exception_id}/reject")
async def reject_exception(
    exception_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    repo = GeofenceExceptionRepo(db)
    ge = await repo.get_by_id(exception_id)
    if not ge:
        return RedirectResponse(url="/geofence", status_code=302)

    await repo.set_status(exception_id, ApprovalStatus.REJECTED, reviewed_by=current_user.id)

    shift_repo = ShiftRepo(db)
    if ge.event == "open":
        await shift_repo.update_open_approval(ge.shift_id, ApprovalStatus.REJECTED)
    elif ge.event == "close":
        await shift_repo.update_close_approval(ge.shift_id, ApprovalStatus.REJECTED)

    return RedirectResponse(url="/geofence", status_code=302)
