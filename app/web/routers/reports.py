from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appeal,
    DefectIncident,
    Point,
    PointDeliveryStat,
    Shift,
    SOSIncident,
    WebUser,
)
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_class=HTMLResponse)
async def reports_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    date_from: str = "",
    date_to: str = "",
    point_id: int = 0,
):
    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()

    # Build summary stats
    shifts_q = select(func.count(Shift.id))
    defects_q = select(func.count(DefectIncident.id))
    sos_q = select(func.count(SOSIncident.id))
    appeals_q = select(func.count(Appeal.id))
    deliveries_q = select(func.sum(PointDeliveryStat.total_count))

    if date_from:
        shifts_q = shifts_q.where(Shift.shift_date >= date_from)
        defects_q = defects_q.where(DefectIncident.incident_date >= date_from)
        sos_q = sos_q.where(SOSIncident.incident_date >= date_from)
        appeals_q = appeals_q.where(Appeal.case_date >= date_from)
        deliveries_q = deliveries_q.where(PointDeliveryStat.stat_date >= date_from)
    if date_to:
        shifts_q = shifts_q.where(Shift.shift_date <= date_to)
        defects_q = defects_q.where(DefectIncident.incident_date <= date_to)
        sos_q = sos_q.where(SOSIncident.incident_date <= date_to)
        appeals_q = appeals_q.where(Appeal.case_date <= date_to)
        deliveries_q = deliveries_q.where(PointDeliveryStat.stat_date <= date_to)
    if point_id:
        shifts_q = shifts_q.where(Shift.point_id == point_id)
        defects_q = defects_q.where(DefectIncident.point_id == point_id)
        sos_q = sos_q.where(SOSIncident.point_id == point_id)
        appeals_q = appeals_q.where(Appeal.point_id == point_id)
        deliveries_q = deliveries_q.where(PointDeliveryStat.point_id == point_id)

    shifts_count = (await db.execute(shifts_q)).scalar() or 0
    defects_count = (await db.execute(defects_q)).scalar() or 0
    sos_count = (await db.execute(sos_q)).scalar() or 0
    appeals_count = (await db.execute(appeals_q)).scalar() or 0
    deliveries_total = (await db.execute(deliveries_q)).scalar() or 0

    # Appeals breakdown
    appealed = (await db.execute(
        select(func.count(Appeal.id)).where(Appeal.status == "appealed")
    )).scalar() or 0
    not_appealed = (await db.execute(
        select(func.count(Appeal.id)).where(Appeal.status == "not_appealed")
    )).scalar() or 0

    # Defects by type
    defect_by_type = {}
    for row in (await db.execute(
        select(DefectIncident.incident_type, func.count(DefectIncident.id))
        .group_by(DefectIncident.incident_type)
    )).all():
        defect_by_type[row[0]] = row[1]

    return templates.TemplateResponse("reports/index.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "reports",
        "points": points,
        "point_id": point_id,
        "date_from": date_from,
        "date_to": date_to,
        "shifts_count": shifts_count,
        "defects_count": defects_count,
        "sos_count": sos_count,
        "appeals_count": appeals_count,
        "deliveries_total": deliveries_total,
        "appealed": appealed,
        "not_appealed": not_appealed,
        "defect_by_type": defect_by_type,
    })
