from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Point, SOSIncident, User, WebUser
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/sos", tags=["sos"])

SOS_STATUSES = [
    ("open", "Открыто"),
    ("resolved", "Решено"),
    ("unresolved", "Не решено"),
    ("on_hold", "На контроле"),
]


@router.get("", response_class=HTMLResponse)
async def list_sos(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    point_id: int = 0,
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    search: str = "",
    page: int = 1,
):
    per_page = 25
    query = select(SOSIncident)

    if point_id:
        query = query.where(SOSIncident.point_id == point_id)
    if status:
        query = query.where(SOSIncident.status == status)
    if date_from:
        query = query.where(SOSIncident.incident_date >= date_from)
    if date_to:
        query = query.where(SOSIncident.incident_date <= date_to)
    if search:
        query = query.where(
            SOSIncident.description.ilike(f"%{search}%")
            | SOSIncident.client_name.ilike(f"%{search}%")
        )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(SOSIncident.incident_date.desc(), SOSIncident.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()
    points_map = {p.id: p for p in points}

    return templates.TemplateResponse("sos/list.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "sos",
        "items": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "points": points,
        "points_map": points_map,
        "point_id": point_id,
        "status": status,
        "date_from": date_from,
        "date_to": date_to,
        "search": search,
        "statuses": SOS_STATUSES,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_sos(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()

    employees_result = await db.execute(select(User).where(User.is_active == True))
    employees = employees_result.scalars().all()

    return templates.TemplateResponse("sos/form.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "sos",
        "item": None,
        "points": points,
        "employees": employees,
        "statuses": SOS_STATUSES,
        "error": None,
    })


@router.post("/new")
async def create_sos(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()

    amount = None
    raw_amount = form.get("total_amount", "").strip()
    if raw_amount:
        try:
            amount = float(raw_amount.replace("р", "").replace(" ", "").replace(",", "."))
        except ValueError:
            pass

    incident = SOSIncident(
        point_id=int(form["point_id"]),
        incident_date=form["incident_date"],
        description=form.get("description", "").strip(),
        client_name=form.get("client_name", "").strip() or None,
        client_phone=form.get("client_phone", "").strip() or None,
        cell_code=form.get("cell_code", "").strip() or None,
        products_raw=form.get("products_raw", "").strip() or None,
        total_amount=amount,
        status=form.get("status", "open"),
        recorded_by_employee_id=int(form["recorded_by_employee_id"]) if form.get("recorded_by_employee_id") else None,
        created_by_user_id=current_user.id,
    )
    db.add(incident)
    await db.commit()
    return RedirectResponse(url="/sos", status_code=302)


@router.get("/{sos_id}", response_class=HTMLResponse)
async def sos_detail(
    sos_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(SOSIncident).where(SOSIncident.id == sos_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url="/sos", status_code=302)

    points_result = await db.execute(select(Point))
    points_map = {p.id: p for p in points_result.scalars().all()}

    users_result = await db.execute(select(User))
    users_map = {u.id: u for u in users_result.scalars().all()}

    return templates.TemplateResponse("sos/detail.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "sos",
        "item": item,
        "points_map": points_map,
        "users_map": users_map,
        "statuses": SOS_STATUSES,
    })


@router.get("/{sos_id}/edit", response_class=HTMLResponse)
async def edit_sos(
    sos_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(SOSIncident).where(SOSIncident.id == sos_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url="/sos", status_code=302)

    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()

    employees_result = await db.execute(select(User).where(User.is_active == True))
    employees = employees_result.scalars().all()

    return templates.TemplateResponse("sos/form.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "sos",
        "item": item,
        "points": points,
        "employees": employees,
        "statuses": SOS_STATUSES,
        "error": None,
    })


@router.post("/{sos_id}/edit")
async def update_sos(
    sos_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(SOSIncident).where(SOSIncident.id == sos_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url="/sos", status_code=302)

    form = await request.form()
    item.point_id = int(form["point_id"])
    item.incident_date = form["incident_date"]
    item.description = form.get("description", "").strip()
    item.client_name = form.get("client_name", "").strip() or None
    item.client_phone = form.get("client_phone", "").strip() or None
    item.cell_code = form.get("cell_code", "").strip() or None
    item.products_raw = form.get("products_raw", "").strip() or None
    item.status = form.get("status", "open")
    item.resolution_comment = form.get("resolution_comment", "").strip() or None
    item.updated_by_user_id = current_user.id

    if item.status == "resolved" and not item.resolved_at:
        item.resolved_at = datetime.utcnow()

    raw_amount = form.get("total_amount", "").strip()
    if raw_amount:
        try:
            item.total_amount = float(raw_amount.replace("р", "").replace(" ", "").replace(",", "."))
        except ValueError:
            pass
    else:
        item.total_amount = None

    await db.commit()
    return RedirectResponse(url=f"/sos/{sos_id}", status_code=302)
