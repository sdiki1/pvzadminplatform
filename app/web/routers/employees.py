from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    EmployeeAlias,
    EmployeePointAssignment,
    PayrollItem,
    PayrollRun,
    Point,
    Shift,
    ShiftConfirmation,
    User,
    WebUser,
)
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_class=HTMLResponse)
async def list_employees(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    search: str = "",
    role: str = "",
    status: str = "",
    page: int = 1,
):
    per_page = 25
    query = select(User)

    if search:
        query = query.where(User.full_name.ilike(f"%{search}%") | User.phone.ilike(f"%{search}%"))
    if role:
        query = query.where(User.role == role)
    if status == "active":
        query = query.where(User.is_active == True)
    elif status == "inactive":
        query = query.where(User.is_active == False)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(User.full_name).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    employees = result.scalars().all()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(request, "employees/list.html", {
        "current_user": current_user,
        "active_page": "employees",
        "items": employees,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "search": search,
        "role": role,
        "status": status,
    })


@router.get("/{employee_id}", response_class=HTMLResponse)
async def employee_detail(
    employee_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(User).where(User.id == employee_id))
    employee = result.scalar_one_or_none()
    if not employee:
        return RedirectResponse(url="/employees", status_code=302)

    # Aliases
    aliases_result = await db.execute(
        select(EmployeeAlias).where(EmployeeAlias.employee_id == employee_id)
    )
    aliases = aliases_result.scalars().all()

    # Assignments with points
    assign_result = await db.execute(
        select(EmployeePointAssignment).where(
            EmployeePointAssignment.user_id == employee_id,
            EmployeePointAssignment.is_active.is_(True),
        )
    )
    assignments = assign_result.scalars().all()

    points_result = await db.execute(select(Point))
    points_map = {p.id: p for p in points_result.scalars().all()}

    # Recent shifts (last 20)
    shifts_result = await db.execute(
        select(Shift).where(Shift.user_id == employee_id)
        .order_by(Shift.shift_date.desc())
        .limit(20)
    )
    recent_shifts = shifts_result.scalars().all()

    # Payroll history (last 10)
    payroll_result = await db.execute(
        select(PayrollItem).where(PayrollItem.user_id == employee_id)
        .order_by(PayrollItem.id.desc())
        .limit(10)
    )
    payroll_items = payroll_result.scalars().all()

    run_ids = [pi.run_id for pi in payroll_items]
    runs_map = {}
    if run_ids:
        runs_result = await db.execute(select(PayrollRun).where(PayrollRun.id.in_(run_ids)))
        runs_map = {r.id: r for r in runs_result.scalars().all()}

    return templates.TemplateResponse(request, "employees/detail.html", {
        "current_user": current_user,
        "active_page": "employees",
        "item": employee,
        "aliases": aliases,
        "assignments": assignments,
        "points_map": points_map,
        "recent_shifts": recent_shifts,
        "payroll_items": payroll_items,
        "runs_map": runs_map,
    })


@router.get("/{employee_id}/edit", response_class=HTMLResponse)
async def edit_employee(
    employee_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(User).where(User.id == employee_id))
    employee = result.scalar_one_or_none()
    if not employee:
        return RedirectResponse(url="/employees", status_code=302)

    points_result = await db.execute(select(Point).where(Point.is_active.is_(True)).order_by(Point.name))
    points = points_result.scalars().all()

    assign_result = await db.execute(
        select(EmployeePointAssignment).where(
            EmployeePointAssignment.user_id == employee_id,
            EmployeePointAssignment.is_active.is_(True),
        )
    )
    assignments = assign_result.scalars().all()
    assignments_map = {a.point_id: a for a in assignments}

    return templates.TemplateResponse(request, "employees/form.html", {
        "current_user": current_user,
        "active_page": "employees",
        "item": employee,
        "points": points,
        "assignments_map": assignments_map,
        "error": None,
    })


@router.post("/{employee_id}/edit")
async def update_employee(
    employee_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(User).where(User.id == employee_id))
    employee = result.scalar_one_or_none()
    if not employee:
        return RedirectResponse(url="/employees", status_code=302)

    form = await request.form()
    employee.full_name = form.get("full_name", "").strip()
    employee.phone = form.get("phone", "").strip() or None
    employee.is_active = form.get("is_active") == "on"

    await db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=302)


@router.post("/{employee_id}/aliases")
async def add_alias(
    employee_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()
    alias = EmployeeAlias(
        employee_id=employee_id,
        alias_text=form.get("alias_text", "").strip(),
        alias_type=form.get("alias_type", "short_name"),
    )
    db.add(alias)
    await db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=302)


@router.post("/{employee_id}/assign")
async def assign_to_point(
    employee_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()
    point_id = int(form.get("point_id", 0))
    shift_rate = Decimal(form.get("shift_rate_rub", "0") or "0")
    hourly_rate = Decimal(form.get("hourly_rate_rub", "0") or "0")
    is_primary = form.get("is_primary") == "on"

    # Check existing
    result = await db.execute(
        select(EmployeePointAssignment).where(
            EmployeePointAssignment.user_id == employee_id,
            EmployeePointAssignment.point_id == point_id,
        )
    )
    assignment = result.scalar_one_or_none()

    if assignment:
        assignment.shift_rate_rub = shift_rate
        assignment.hourly_rate_rub = hourly_rate
        assignment.is_primary = is_primary
        assignment.is_active = True
    else:
        assignment = EmployeePointAssignment(
            user_id=employee_id,
            point_id=point_id,
            shift_rate_rub=shift_rate,
            hourly_rate_rub=hourly_rate,
            is_primary=is_primary,
            is_active=True,
        )
        db.add(assignment)

    await db.commit()
    return RedirectResponse(url=f"/employees/{employee_id}", status_code=302)
