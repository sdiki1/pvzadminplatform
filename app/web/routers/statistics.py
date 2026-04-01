from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    DailyStatMetricDef,
    DailyStatMetricValue,
    DailyStatReport,
    Point,
    WebUser,
)
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/statistics", tags=["statistics"])


@router.get("", response_class=HTMLResponse)
async def list_statistics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    point_id: int = 0,
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
):
    per_page = 30
    query = select(DailyStatReport)

    if point_id:
        query = query.where(DailyStatReport.point_id == point_id)
    if date_from:
        query = query.where(DailyStatReport.stat_date >= date_from)
    if date_to:
        query = query.where(DailyStatReport.stat_date <= date_to)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(DailyStatReport.stat_date.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    reports = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()
    points_map = {p.id: p for p in points}

    # Get metric values for reports
    report_ids = [r.id for r in reports]
    metrics_map = {}
    if report_ids:
        vals_result = await db.execute(
            select(DailyStatMetricValue).where(DailyStatMetricValue.report_id.in_(report_ids))
        )
        for v in vals_result.scalars().all():
            metrics_map.setdefault(v.report_id, []).append(v)

    # Metric defs
    defs_result = await db.execute(
        select(DailyStatMetricDef).where(DailyStatMetricDef.is_active == True).order_by(DailyStatMetricDef.sort_order)
    )
    metric_defs = defs_result.scalars().all()
    defs_map = {d.id: d for d in metric_defs}

    return templates.TemplateResponse(request, "statistics/index.html", {"current_user": current_user,
        "active_page": "statistics",
        "items": reports,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "points": points,
        "points_map": points_map,
        "metrics_map": metrics_map,
        "metric_defs": metric_defs,
        "defs_map": defs_map,
        "point_id": point_id,
        "date_from": date_from,
        "date_to": date_to})


@router.get("/new", response_class=HTMLResponse)
async def new_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()

    defs_result = await db.execute(
        select(DailyStatMetricDef).where(DailyStatMetricDef.is_active == True).order_by(DailyStatMetricDef.sort_order)
    )
    metric_defs = defs_result.scalars().all()

    return templates.TemplateResponse(request, "statistics/form.html", {"current_user": current_user,
        "active_page": "statistics",
        "item": None,
        "points": points,
        "metric_defs": metric_defs,
        "error": None})


@router.post("/new")
async def create_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()
    report = DailyStatReport(
        point_id=int(form["point_id"]),
        stat_date=date.fromisoformat(str(form["stat_date"])),
        comment=form.get("comment", "").strip() or None,
        source="manual",
        created_by_user_id=current_user.id,
    )
    db.add(report)
    await db.flush()

    # Save metric values
    defs_result = await db.execute(
        select(DailyStatMetricDef).where(DailyStatMetricDef.is_active == True)
    )
    for metric_def in defs_result.scalars().all():
        raw_val = form.get(f"metric_{metric_def.id}", "").strip()
        if raw_val:
            val = DailyStatMetricValue(
                report_id=report.id,
                metric_def_id=metric_def.id,
                raw_value=raw_val,
            )
            if metric_def.value_type == "integer":
                try:
                    val.value_int = int(raw_val.replace(" ", ""))
                except ValueError:
                    pass
            elif metric_def.value_type == "decimal":
                try:
                    val.value_decimal = float(raw_val.replace(" ", "").replace(",", "."))
                except ValueError:
                    pass
            elif metric_def.value_type == "boolean":
                val.value_bool = raw_val.lower() in ("да", "yes", "true", "1")
            else:
                val.value_text = raw_val
            db.add(val)

    await db.commit()
    return RedirectResponse(url="/statistics", status_code=302)
