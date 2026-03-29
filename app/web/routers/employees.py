from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmployeeAlias, Point, User, WebUser
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

    return templates.TemplateResponse("employees/list.html", {
        "request": request,
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

    aliases_result = await db.execute(
        select(EmployeeAlias).where(EmployeeAlias.employee_id == employee_id)
    )
    aliases = aliases_result.scalars().all()

    return templates.TemplateResponse("employees/detail.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "employees",
        "item": employee,
        "aliases": aliases,
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

    return templates.TemplateResponse("employees/form.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "employees",
        "item": employee,
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
