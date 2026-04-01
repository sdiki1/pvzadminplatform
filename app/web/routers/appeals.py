from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appeal, AppealFeedback, Point, User, WebUser
from app.utils.parsing import parse_date
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/appeals", tags=["appeals"])

APPEAL_TYPES = [
    ("defect", "Брак"),
    ("substitution", "Подмена"),
    ("stuck", "Зависшие"),
    ("other", "Другое"),
]

APPEAL_STATUSES = [
    ("none", "Без статуса"),
    ("in_progress", "В работе"),
    ("appealed", "Оспорено"),
    ("not_appealed", "Не оспорено"),
    ("closed", "Закрыто"),
]

APPEAL_TYPE_LABELS = dict(APPEAL_TYPES)
APPEAL_STATUS_LABELS = dict(APPEAL_STATUSES)


@router.get("", response_class=HTMLResponse)
async def list_appeals(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    point_id: int = 0,
    status: str = "",
    appeal_type: str = "",
    date_from: str = "",
    date_to: str = "",
    search: str = "",
    page: int = 1,
):
    per_page = 25
    query = select(Appeal)
    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if point_id:
        query = query.where(Appeal.point_id == point_id)
    if status:
        query = query.where(Appeal.status == status)
    if appeal_type:
        query = query.where(Appeal.appeal_type == appeal_type)
    if parsed_date_from:
        query = query.where(Appeal.case_date >= parsed_date_from)
    if parsed_date_to:
        query = query.where(Appeal.case_date <= parsed_date_to)
    if search:
        query = query.where(
            Appeal.barcode.ilike(f"%{search}%")
            | Appeal.ticket_number.ilike(f"%{search}%")
            | Appeal.assigned_manager_raw.ilike(f"%{search}%")
        )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(Appeal.case_date.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()
    points_map = {p.id: p for p in points}

    users_result = await db.execute(select(User))
    users_map = {u.id: u for u in users_result.scalars().all()}

    return templates.TemplateResponse(request, "appeals/list.html", {"current_user": current_user,
        "active_page": "appeals",
        "items": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "points": points,
        "points_map": points_map,
        "users_map": users_map,
        "point_id": point_id,
        "status": status,
        "appeal_type": appeal_type,
        "date_from": date_from,
        "date_to": date_to,
        "search": search,
        "appeal_types": APPEAL_TYPES,
        "statuses": APPEAL_STATUSES,
        "appeal_type_labels": APPEAL_TYPE_LABELS,
        "status_labels": APPEAL_STATUS_LABELS})


@router.get("/new", response_class=HTMLResponse)
async def new_appeal(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()

    employees_result = await db.execute(select(User).where(User.is_active == True))
    employees = employees_result.scalars().all()

    return templates.TemplateResponse(request, "appeals/form.html", {"current_user": current_user,
        "active_page": "appeals",
        "item": None,
        "points": points,
        "employees": employees,
        "appeal_types": APPEAL_TYPES,
        "statuses": APPEAL_STATUSES,
        "appeal_type_labels": APPEAL_TYPE_LABELS,
        "status_labels": APPEAL_STATUS_LABELS,
        "error": None})


@router.post("/new")
async def create_appeal(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()
    case_date = parse_date(form.get("case_date")) or date.today()
    deadline_date = parse_date(form.get("deadline_date"))

    amount = None
    raw_amount = form.get("amount", "").strip()
    if raw_amount:
        try:
            amount = float(raw_amount.replace("р", "").replace(" ", "").replace(",", "."))
        except ValueError:
            pass

    assigned_manager_employee_id = None
    raw_manager_id = str(form.get("assigned_manager_employee_id", "")).strip()
    if raw_manager_id.isdigit():
        assigned_manager_employee_id = int(raw_manager_id)

    assigned_manager_raw = form.get("assigned_manager_raw", "").strip() or None
    if not assigned_manager_employee_id and assigned_manager_raw:
        manager_result = await db.execute(
            select(User).where(
                User.last_name.is_not(None),
                User.last_name.ilike(assigned_manager_raw),
            )
        )
        manager = manager_result.scalar_one_or_none()
        if manager:
            assigned_manager_employee_id = manager.id

    appeal = Appeal(
        case_date=case_date,
        point_id=int(form["point_id"]),
        appeal_type=form.get("appeal_type", "other"),
        barcode=form.get("barcode", "").strip() or None,
        ticket_number=form.get("ticket_number", "").strip() or None,
        amount=amount,
        status=form.get("status", "none"),
        assigned_manager_employee_id=assigned_manager_employee_id,
        assigned_manager_raw=assigned_manager_raw,
        non_appeal_reason=form.get("non_appeal_reason", "").strip() or None,
        charge_to_manager=form.get("charge_to_manager") == "on",
        charge_comment=form.get("charge_comment", "").strip() or None,
        feedback_from_nadezhda=form.get("feedback_from_nadezhda", "").strip() or None,
        feedback_from_anna=form.get("feedback_from_anna", "").strip() or None,
        deadline_date=deadline_date,
        result_comment=form.get("result_comment", "").strip() or None,
        created_by_user_id=current_user.id,
    )
    db.add(appeal)
    await db.commit()
    return RedirectResponse(url="/appeals", status_code=302)


@router.get("/{appeal_id}", response_class=HTMLResponse)
async def appeal_detail(
    appeal_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(Appeal).where(Appeal.id == appeal_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url="/appeals", status_code=302)

    feedback_result = await db.execute(
        select(AppealFeedback).where(AppealFeedback.appeal_id == appeal_id).order_by(AppealFeedback.created_at)
    )
    feedbacks = feedback_result.scalars().all()

    points_result = await db.execute(select(Point))
    points_map = {p.id: p for p in points_result.scalars().all()}

    users_result = await db.execute(select(User))
    users_map = {u.id: u for u in users_result.scalars().all()}

    return templates.TemplateResponse(request, "appeals/detail.html", {"current_user": current_user,
        "active_page": "appeals",
        "item": item,
        "feedbacks": feedbacks,
        "points_map": points_map,
        "users_map": users_map,
        "appeal_types": APPEAL_TYPES,
        "statuses": APPEAL_STATUSES,
        "appeal_type_labels": APPEAL_TYPE_LABELS,
        "status_labels": APPEAL_STATUS_LABELS})


@router.post("/{appeal_id}/feedback")
async def add_feedback(
    appeal_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()
    fb = AppealFeedback(
        appeal_id=appeal_id,
        reviewer_name=current_user.full_name,
        reviewer_user_id=current_user.id,
        reviewer_role=current_user.role,
        feedback_text=form.get("feedback_text", "").strip(),
    )
    db.add(fb)
    await db.commit()
    return RedirectResponse(url=f"/appeals/{appeal_id}", status_code=302)
