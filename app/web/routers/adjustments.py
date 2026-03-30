from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdjustmentType, ManualAdjustment, User
from app.web.deps import get_current_user, get_db, require_manager

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/adjustments", tags=["adjustments"])

ADJUSTMENT_TYPES = [
    ("bonus", "Премия"),
    ("deduction", "Удержание"),
    ("correction", "Корректировка"),
]


@router.get("", response_class=HTMLResponse)
async def list_adjustments(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
    employee_id: str = "",
    adj_type: str = "",
    page: int = 1,
):
    per_page = 25
    query = select(ManualAdjustment)

    if employee_id:
        query = query.where(ManualAdjustment.user_id == int(employee_id))
    if adj_type:
        query = query.where(ManualAdjustment.adjustment_type == adj_type)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(ManualAdjustment.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    users_result = await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.full_name))
    employees = users_result.scalars().all()
    users_map = {u.id: u for u in employees}

    return templates.TemplateResponse(request, "adjustments/list.html", {
        "current_user": current_user,
        "active_page": "adjustments",
        "items": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "employees": employees,
        "users_map": users_map,
        "employee_id": employee_id,
        "adj_type": adj_type,
        "adjustment_types": ADJUSTMENT_TYPES,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_adjustment(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    users_result = await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.full_name))
    employees = users_result.scalars().all()

    return templates.TemplateResponse(request, "adjustments/form.html", {
        "current_user": current_user,
        "active_page": "adjustments",
        "item": None,
        "employees": employees,
        "adjustment_types": ADJUSTMENT_TYPES,
        "error": None,
    })


@router.post("/new")
async def create_adjustment(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    form = await request.form()

    user_id = form.get("user_id")
    if not user_id:
        users_result = await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.full_name))
        return templates.TemplateResponse(request, "adjustments/form.html", {
            "current_user": current_user,
            "active_page": "adjustments",
            "item": None,
            "employees": users_result.scalars().all(),
            "adjustment_types": ADJUSTMENT_TYPES,
            "error": "Выберите сотрудника",
        })

    try:
        period_start = date.fromisoformat(form.get("period_start", ""))
        period_end = date.fromisoformat(form.get("period_end", ""))
    except (ValueError, TypeError):
        users_result = await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.full_name))
        return templates.TemplateResponse(request, "adjustments/form.html", {
            "current_user": current_user,
            "active_page": "adjustments",
            "item": None,
            "employees": users_result.scalars().all(),
            "adjustment_types": ADJUSTMENT_TYPES,
            "error": "Укажите корректные даты периода",
        })

    adj = ManualAdjustment(
        user_id=int(user_id),
        period_start=period_start,
        period_end=period_end,
        amount_rub=Decimal(form.get("amount_rub", "0")),
        adjustment_type=AdjustmentType(form.get("adjustment_type", "bonus")),
        comment=form.get("comment", "").strip() or None,
        created_by=current_user.id,
    )
    db.add(adj)
    await db.commit()

    return RedirectResponse(url="/adjustments", status_code=302)
