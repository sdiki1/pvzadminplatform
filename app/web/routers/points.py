from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Marketplace, Point, User, WebUser
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/points", tags=["points"])


@router.get("", response_class=HTMLResponse)
async def list_points(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    search: str = "",
    brand: str = "",
    status: str = "",
    page: int = 1,
):
    per_page = 25
    query = select(Point)

    if search:
        query = query.where(Point.name.ilike(f"%{search}%") | Point.address.ilike(f"%{search}%"))
    if brand:
        query = query.where(Point.brand == brand)
    if status == "active":
        query = query.where(Point.is_active == True)
    elif status == "inactive":
        query = query.where(Point.is_active == False)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(Point.name).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    points = result.scalars().all()

    total_pages = max(1, (total + per_page - 1) // per_page)

    mp_result = await db.execute(select(Marketplace).where(Marketplace.is_active == True))
    marketplaces = mp_result.scalars().all()

    return templates.TemplateResponse("points/list.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "points",
        "items": points,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "search": search,
        "brand": brand,
        "status": status,
        "marketplaces": marketplaces,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_point(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    mp_result = await db.execute(select(Marketplace).where(Marketplace.is_active == True))
    marketplaces = mp_result.scalars().all()
    return templates.TemplateResponse("points/form.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "points",
        "item": None,
        "marketplaces": marketplaces,
        "error": None,
    })


@router.post("/new")
async def create_point(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()
    point = Point(
        name=form.get("name", "").strip(),
        address=form.get("address", "").strip(),
        brand=form.get("brand", "wb"),
        latitude=float(form.get("latitude") or 0),
        longitude=float(form.get("longitude") or 0),
        radius_m=int(form.get("radius_m") or 150),
        work_start=form.get("work_start") or "09:00",
        work_end=form.get("work_end") or "21:00",
        is_active=form.get("is_active") == "on",
        short_name=form.get("short_name", "").strip() or None,
        address_normalized=form.get("address_normalized", "").strip() or form.get("address", "").strip(),
        code=form.get("code", "").strip() or None,
        comment=form.get("comment", "").strip() or None,
    )
    if form.get("marketplace_id"):
        point.marketplace_id = int(form["marketplace_id"])
    db.add(point)
    await db.commit()
    return RedirectResponse(url="/points", status_code=302)


@router.get("/{point_id}", response_class=HTMLResponse)
async def point_detail(
    point_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(Point).where(Point.id == point_id))
    point = result.scalar_one_or_none()
    if not point:
        return RedirectResponse(url="/points", status_code=302)

    mp_result = await db.execute(select(Marketplace).where(Marketplace.is_active == True))
    marketplaces = mp_result.scalars().all()

    return templates.TemplateResponse("points/detail.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "points",
        "item": point,
        "marketplaces": marketplaces,
    })


@router.get("/{point_id}/edit", response_class=HTMLResponse)
async def edit_point(
    point_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(Point).where(Point.id == point_id))
    point = result.scalar_one_or_none()
    if not point:
        return RedirectResponse(url="/points", status_code=302)

    mp_result = await db.execute(select(Marketplace).where(Marketplace.is_active == True))
    marketplaces = mp_result.scalars().all()

    return templates.TemplateResponse("points/form.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "points",
        "item": point,
        "marketplaces": marketplaces,
        "error": None,
    })


@router.post("/{point_id}/edit")
async def update_point(
    point_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(Point).where(Point.id == point_id))
    point = result.scalar_one_or_none()
    if not point:
        return RedirectResponse(url="/points", status_code=302)

    form = await request.form()
    point.name = form.get("name", "").strip()
    point.address = form.get("address", "").strip()
    point.brand = form.get("brand", "wb")
    point.latitude = float(form.get("latitude") or 0)
    point.longitude = float(form.get("longitude") or 0)
    point.radius_m = int(form.get("radius_m") or 150)
    point.work_start = form.get("work_start") or "09:00"
    point.work_end = form.get("work_end") or "21:00"
    point.is_active = form.get("is_active") == "on"
    point.short_name = form.get("short_name", "").strip() or None
    point.address_normalized = form.get("address_normalized", "").strip() or point.address
    point.code = form.get("code", "").strip() or None
    point.comment = form.get("comment", "").strip() or None
    if form.get("marketplace_id"):
        point.marketplace_id = int(form["marketplace_id"])
    else:
        point.marketplace_id = None

    await db.commit()
    return RedirectResponse(url=f"/points/{point_id}", status_code=302)
