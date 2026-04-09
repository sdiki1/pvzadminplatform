from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import BrandEnum, EmployeePointAssignment, Point, User
from app.web.deps import get_db, require_admin

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/salary", tags=["salary"])

BONUS_TYPE_LABELS = {
    None: "Нет",
    1: "Тип 1 — фикс. надбавка А",
    2: "Тип 2 — фикс. надбавка Б",
    3: "Тип 3 — за любой тикет",
}


@router.get("", response_class=HTMLResponse)
async def salary_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    settings = get_settings()

    # All active employees
    users_result = await db.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.full_name)
    )
    users = users_result.scalars().all()

    # All points
    points_result = await db.execute(select(Point).order_by(Point.name))
    points = points_result.scalars().all()
    points_map = {p.id: p for p in points}

    # All active assignments
    asgn_result = await db.execute(
        select(EmployeePointAssignment).where(EmployeePointAssignment.is_active.is_(True))
    )
    all_assignments = asgn_result.scalars().all()

    # Group assignments by user_id
    from collections import defaultdict
    assignments_by_user: dict[int, list[EmployeePointAssignment]] = defaultdict(list)
    for a in all_assignments:
        assignments_by_user[a.user_id].append(a)

    # Separate WB and Ozon points for the rules card
    wb_points = [p for p in points if p.brand == BrandEnum.WB]
    ozon_points = [p for p in points if p.brand == BrandEnum.OZON]

    return templates.TemplateResponse(request, "salary/index.html", {
        "current_user": current_user,
        "active_page": "salary",
        "users": users,
        "points_map": points_map,
        "assignments_by_user": dict(assignments_by_user),
        "wb_points": wb_points,
        "ozon_points": ozon_points,
        "bonus_type_labels": BONUS_TYPE_LABELS,
        # Global rules from settings
        "wb_issue_bonus_step": settings.wb_issue_bonus_step,
        "wb_issue_bonus_amount": settings.wb_issue_bonus_amount,
        "manager_bonus_1": settings.manager_bonus_1,
        "manager_bonus_2": settings.manager_bonus_2,
        "manager_bonus_3_per_ticket": settings.manager_bonus_3_per_ticket,
    })


def _parse_rate(raw: str) -> Decimal:
    try:
        return Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def _parse_optional_rate(raw: str) -> Decimal | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None


@router.post("/employee/{user_id}/rates/wb")
async def update_user_rates_wb(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/salary", status_code=302)

    form = await request.form()
    user.shift_rate_rub_wb = _parse_rate(str(form.get("shift_rate_rub_wb", "0")))
    user.hourly_rate_rub_wb = _parse_optional_rate(str(form.get("hourly_rate_rub_wb", "")))
    await db.commit()
    return RedirectResponse(url="/salary#user-" + str(user_id), status_code=302)


@router.post("/employee/{user_id}/rates/ozon")
async def update_user_rates_ozon(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/salary", status_code=302)

    form = await request.form()
    user.shift_rate_rub_ozon = _parse_rate(str(form.get("shift_rate_rub_ozon", "0")))
    user.hourly_rate_rub_ozon = _parse_optional_rate(str(form.get("hourly_rate_rub_ozon", "")))
    await db.commit()
    return RedirectResponse(url="/salary#user-" + str(user_id), status_code=302)


@router.post("/employee/{user_id}/bonus-type")
async def update_bonus_type(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/salary", status_code=302)

    form = await request.form()
    raw = str(form.get("manager_bonus_type", "")).strip()
    user.manager_bonus_type = int(raw) if raw and raw.isdigit() else None
    await db.commit()

    return RedirectResponse(url="/salary#user-" + str(user_id), status_code=302)


@router.post("/employee/{user_id}/add-assignment")
async def add_assignment(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Add a new point assignment for an employee."""
    result = await db.execute(select(User).where(User.id == user_id))
    if not result.scalar_one_or_none():
        return RedirectResponse(url="/salary", status_code=302)

    form = await request.form()
    point_id_raw = str(form.get("point_id", "")).strip()
    if not point_id_raw.isdigit():
        return RedirectResponse(url="/salary", status_code=302)
    point_id = int(point_id_raw)

    # Check not already assigned
    existing = await db.execute(
        select(EmployeePointAssignment).where(
            EmployeePointAssignment.user_id == user_id,
            EmployeePointAssignment.point_id == point_id,
        )
    )
    asgn = existing.scalar_one_or_none()
    if asgn:
        asgn.is_active = True
    else:
        asgn = EmployeePointAssignment(
            user_id=user_id,
            point_id=point_id,
            shift_rate_rub=Decimal("0"),
            hourly_rate_rub=None,
            is_primary=False,
            is_active=True,
        )
        db.add(asgn)
    await db.commit()

    return RedirectResponse(url="/salary#user-" + str(user_id), status_code=302)


@router.post("/assignment/{assignment_id}/remove")
async def remove_assignment(
    assignment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(
        select(EmployeePointAssignment).where(EmployeePointAssignment.id == assignment_id)
    )
    assignment = result.scalar_one_or_none()
    if assignment:
        user_id = assignment.user_id
        assignment.is_active = False
        await db.commit()
        return RedirectResponse(url="/salary#user-" + str(user_id), status_code=302)
    return RedirectResponse(url="/salary", status_code=302)
