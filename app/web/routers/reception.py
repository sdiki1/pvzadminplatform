from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Point, ReceptionStat, WebUser
from app.web.deps import get_current_user, get_db, is_restricted_manager

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/reception", tags=["reception"])


@router.get("", response_class=HTMLResponse)
async def reception_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    point_id: int = 0,
    year: int = 0,
    month: int = 0,
):
    today = date.today()
    if not year:
        year = today.year
    if not month:
        month = today.month

    points_result = await db.execute(select(Point).where(Point.is_active == True).order_by(Point.name))
    points = points_result.scalars().all()

    # If no point selected, use first
    if not point_id and points:
        point_id = points[0].id

    # Days in month
    _, days_in_month = calendar.monthrange(year, month)
    dates = [date(year, month, d) for d in range(1, days_in_month + 1)]

    # Load stats for this point+month
    stats_result = await db.execute(
        select(ReceptionStat).where(
            ReceptionStat.point_id == point_id,
            ReceptionStat.stat_date >= date(year, month, 1),
            ReceptionStat.stat_date <= date(year, month, days_in_month),
        )
    )
    stats_by_date: dict[date, ReceptionStat] = {s.stat_date: s for s in stats_result.scalars().all()}

    # Build grid data
    grid = []
    for d in dates:
        s = stats_by_date.get(d)
        grid.append({
            "date": d,
            "day": d.day,
            "items_given": s.items_given if s else None,
            "clients_count": s.clients_count if s else None,
            "acceptance_amount": float(s.acceptance_amount) if s and s.acceptance_amount is not None else None,
        })

    # Month nav
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    month_names = ["Январь","Февраль","Март","Апрель","Май","Июнь",
                   "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]
    # 0=Пн … 6=Вс
    day_names = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]

    return templates.TemplateResponse(request, "reception/index.html", {
        "current_user": current_user,
        "active_page": "reception",
        "points": points,
        "point_id": point_id,
        "year": year,
        "month": month,
        "month_name": month_names[month - 1],
        "grid": grid,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "today_str": date.today().strftime('%Y-%m-%d'),
        "day_names": day_names,
    })


@router.post("/save")
async def save_cell(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    """AJAX endpoint: save a single cell value."""
    if is_restricted_manager(current_user):
        return JSONResponse({"error": "permission denied"}, status_code=403)

    data = await request.json()
    point_id = int(data.get("point_id", 0))
    field = str(data.get("field", ""))
    raw_value = str(data.get("value", "")).strip()
    try:
        stat_date = date.fromisoformat(str(data.get("date", "")))
    except (ValueError, TypeError):
        return JSONResponse({"error": "invalid date"}, status_code=400)

    if field not in ("items_given", "clients_count", "acceptance_amount"):
        return JSONResponse({"error": "invalid field"}, status_code=400)

    # Upsert
    stat = (await db.execute(
        select(ReceptionStat).where(
            ReceptionStat.point_id == point_id,
            ReceptionStat.stat_date == stat_date,
        )
    )).scalar_one_or_none()

    if not stat:
        stat = ReceptionStat(point_id=point_id, stat_date=stat_date)
        db.add(stat)

    if not raw_value:
        setattr(stat, field, None)
    elif field in ("items_given", "clients_count"):
        try:
            setattr(stat, field, int(raw_value))
        except ValueError:
            return JSONResponse({"error": "invalid integer"}, status_code=400)
    else:
        try:
            setattr(stat, field, Decimal(raw_value.replace(",", ".")))
        except InvalidOperation:
            return JSONResponse({"error": "invalid number"}, status_code=400)

    await db.commit()
    return JSONResponse({"ok": True})
