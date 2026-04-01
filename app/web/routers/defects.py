from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DefectIncident, Point, User, WebUser
from app.utils.parsing import parse_date
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/defects", tags=["defects"])

INCIDENT_TYPES = [
    ("defect", "Брак"),
    ("mismatch", "Несоответствие"),
    ("substitution", "Подмена"),
    ("spill", "Разлив"),
    ("damage", "Повреждение"),
    ("incomplete_set", "Некомплект"),
    ("other", "Другое"),
]

DETECTED_BY = [
    ("client", "Клиент"),
    ("employee", "Сотрудник"),
    ("unknown", "Неизвестно"),
    ("other", "Другое"),
]

DETECTED_STAGES = [
    ("intake", "При приёмке"),
    ("issue", "При выдаче"),
    ("receipt", "При получении"),
    ("check", "При проверке"),
    ("return", "При возврате"),
    ("return_home", "Возврат из дома"),
    ("other", "Другое"),
]

STATUSES = [
    ("new", "Новое"),
    ("in_progress", "В работе"),
    ("closed", "Закрыто"),
    ("cancelled", "Отменено"),
]

# Lookup dicts — passed to every template for label resolution
INCIDENT_TYPE_LABELS = dict(INCIDENT_TYPES)
DETECTED_BY_LABELS = dict(DETECTED_BY)
DETECTED_STAGE_LABELS = dict(DETECTED_STAGES)
STATUS_LABELS = dict(STATUSES)

def _labels() -> dict:
    return {
        "incident_type_labels": INCIDENT_TYPE_LABELS,
        "detected_by_labels": DETECTED_BY_LABELS,
        "detected_stage_labels": DETECTED_STAGE_LABELS,
        "status_labels": STATUS_LABELS,
    }


@router.get("", response_class=HTMLResponse)
async def list_defects(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    point_id: int = 0,
    status: str = "",
    incident_type: str = "",
    date_from: str = "",
    date_to: str = "",
    search: str = "",
    page: int = 1,
):
    per_page = 25
    query = select(DefectIncident)
    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if point_id:
        query = query.where(DefectIncident.point_id == point_id)
    if status:
        query = query.where(DefectIncident.status == status)
    if incident_type:
        query = query.where(DefectIncident.incident_type == incident_type)
    if parsed_date_from:
        query = query.where(DefectIncident.incident_date >= parsed_date_from)
    if parsed_date_to:
        query = query.where(DefectIncident.incident_date <= parsed_date_to)
    if search:
        query = query.where(
            DefectIncident.barcode.ilike(f"%{search}%")
            | DefectIncident.product_title.ilike(f"%{search}%")
            | DefectIncident.problem_description.ilike(f"%{search}%")
        )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(DefectIncident.incident_date.desc(), DefectIncident.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()
    points_map = {p.id: p for p in points}

    return templates.TemplateResponse(request, "defects/list.html", {"current_user": current_user,
        "active_page": "defects",
        "items": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "points": points,
        "points_map": points_map,
        "point_id": point_id,
        "status": status,
        "incident_type": incident_type,
        "date_from": date_from,
        "date_to": date_to,
        "search": search,
        "incident_types": INCIDENT_TYPES,
        "statuses": STATUSES,
        **_labels()})


@router.get("/new", response_class=HTMLResponse)
async def new_defect(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()

    employees_result = await db.execute(select(User).where(User.is_active == True))
    employees = employees_result.scalars().all()

    return templates.TemplateResponse(request, "defects/form.html", {"current_user": current_user,
        "active_page": "defects",
        "item": None,
        "points": points,
        "employees": employees,
        "incident_types": INCIDENT_TYPES,
        "detected_by": DETECTED_BY,
        "detected_stages": DETECTED_STAGES,
        "statuses": STATUSES,
        "error": None,
        **_labels()})


@router.post("/new")
async def create_defect(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()
    incident_date = parse_date(form.get("incident_date")) or date.today()

    amount = None
    raw_amount = form.get("amount", "").strip()
    if raw_amount:
        try:
            amount = float(raw_amount.replace("р", "").replace(" ", "").replace(",", "."))
        except ValueError:
            pass

    incident = DefectIncident(
        point_id=int(form["point_id"]),
        incident_date=incident_date,
        detected_by_role=form.get("detected_by_role", "unknown"),
        detected_stage=form.get("detected_stage", "other"),
        incident_type=form.get("incident_type", "other"),
        barcode=form.get("barcode", "").strip() or None,
        product_title=form.get("product_title", "").strip() or None,
        problem_description=form.get("problem_description", "").strip() or None,
        action_type=form.get("action_type", "").strip() or None,
        action_comment=form.get("action_comment", "").strip() or None,
        amount=amount,
        status=form.get("status", "new"),
        recorded_by_employee_id=int(form["recorded_by_employee_id"]) if form.get("recorded_by_employee_id") else None,
        created_by_user_id=current_user.id,
    )
    db.add(incident)
    await db.commit()
    return RedirectResponse(url="/defects", status_code=302)


@router.get("/{defect_id}", response_class=HTMLResponse)
async def defect_detail(
    defect_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(DefectIncident).where(DefectIncident.id == defect_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url="/defects", status_code=302)

    points_result = await db.execute(select(Point))
    points_map = {p.id: p for p in points_result.scalars().all()}

    users_result = await db.execute(select(User))
    users_map = {u.id: u for u in users_result.scalars().all()}

    return templates.TemplateResponse(request, "defects/detail.html", {"current_user": current_user,
        "active_page": "defects",
        "item": item,
        "points_map": points_map,
        "users_map": users_map,
        "incident_types": INCIDENT_TYPES,
        "detected_by": DETECTED_BY,
        "detected_stages": DETECTED_STAGES,
        "statuses": STATUSES,
        **_labels()})


@router.get("/{defect_id}/edit", response_class=HTMLResponse)
async def edit_defect(
    defect_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(DefectIncident).where(DefectIncident.id == defect_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url="/defects", status_code=302)

    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()

    employees_result = await db.execute(select(User).where(User.is_active == True))
    employees = employees_result.scalars().all()

    return templates.TemplateResponse(request, "defects/form.html", {"current_user": current_user,
        "active_page": "defects",
        "item": item,
        "points": points,
        "employees": employees,
        "incident_types": INCIDENT_TYPES,
        "detected_by": DETECTED_BY,
        "detected_stages": DETECTED_STAGES,
        "statuses": STATUSES,
        "error": None,
        **_labels()})


@router.post("/{defect_id}/edit")
async def update_defect(
    defect_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(DefectIncident).where(DefectIncident.id == defect_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url="/defects", status_code=302)

    form = await request.form()
    item.point_id = int(form["point_id"])
    item.incident_date = parse_date(form.get("incident_date")) or item.incident_date
    item.detected_by_role = form.get("detected_by_role", "unknown")
    item.detected_stage = form.get("detected_stage", "other")
    item.incident_type = form.get("incident_type", "other")
    item.barcode = form.get("barcode", "").strip() or None
    item.product_title = form.get("product_title", "").strip() or None
    item.problem_description = form.get("problem_description", "").strip() or None
    item.action_type = form.get("action_type", "").strip() or None
    item.action_comment = form.get("action_comment", "").strip() or None
    item.status = form.get("status", "new")
    item.resolution_comment = form.get("resolution_comment", "").strip() or None
    item.updated_by_user_id = current_user.id

    raw_amount = form.get("amount", "").strip()
    if raw_amount:
        try:
            item.amount = float(raw_amount.replace("р", "").replace(" ", "").replace(",", "."))
        except ValueError:
            pass
    else:
        item.amount = None

    if form.get("recorded_by_employee_id"):
        item.recorded_by_employee_id = int(form["recorded_by_employee_id"])

    await db.commit()
    return RedirectResponse(url=f"/defects/{defect_id}", status_code=302)
