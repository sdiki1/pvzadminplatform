from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Point, PointDeliveryStat, WebUser
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


def parse_delivery_raw(raw: str) -> int:
    """Parse raw delivery string like '91+64' into total 155."""
    if not raw or not raw.strip():
        return 0
    raw = raw.strip()
    try:
        return int(raw)
    except ValueError:
        pass
    # Try sum expression like "91+64"
    parts = re.split(r'\s*\+\s*', raw)
    try:
        return sum(int(p) for p in parts if p.strip())
    except ValueError:
        return 0


@router.get("", response_class=HTMLResponse)
async def list_deliveries(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    point_id: int = 0,
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
):
    per_page = 30
    query = select(PointDeliveryStat)

    if point_id:
        query = query.where(PointDeliveryStat.point_id == point_id)
    if date_from:
        query = query.where(PointDeliveryStat.stat_date >= date_from)
    if date_to:
        query = query.where(PointDeliveryStat.stat_date <= date_to)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(PointDeliveryStat.stat_date.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()
    points_map = {p.id: p for p in points}

    return templates.TemplateResponse(request, "deliveries/list.html", {"current_user": current_user,
        "active_page": "deliveries",
        "items": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "points": points,
        "points_map": points_map,
        "point_id": point_id,
        "date_from": date_from,
        "date_to": date_to})


@router.get("/new", response_class=HTMLResponse)
async def new_delivery(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()

    return templates.TemplateResponse(request, "deliveries/form.html", {"current_user": current_user,
        "active_page": "deliveries",
        "item": None,
        "points": points,
        "error": None})


@router.post("/new")
async def create_delivery(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()

    night_raw = form.get("night_raw", "").strip() or None
    morning_raw = form.get("morning_raw", "").strip() or None
    day_raw = form.get("day_raw", "").strip() or None
    evening_raw = form.get("evening_raw", "").strip() or None

    night_total = parse_delivery_raw(night_raw) if night_raw else None
    morning_total = parse_delivery_raw(morning_raw) if morning_raw else None
    day_total = parse_delivery_raw(day_raw) if day_raw else None
    evening_total = parse_delivery_raw(evening_raw) if evening_raw else None

    total_count = sum(v for v in [night_total, morning_total, day_total, evening_total] if v is not None)

    stat = PointDeliveryStat(
        point_id=int(form["point_id"]),
        stat_date=form["stat_date"],
        night_raw=night_raw,
        night_total=night_total,
        morning_raw=morning_raw,
        morning_total=morning_total,
        day_raw=day_raw,
        day_total=day_total,
        evening_raw=evening_raw,
        evening_total=evening_total,
        total_count=total_count,
        comment=form.get("comment", "").strip() or None,
        created_by_user_id=current_user.id,
    )
    db.add(stat)
    await db.commit()
    return RedirectResponse(url="/deliveries", status_code=302)
