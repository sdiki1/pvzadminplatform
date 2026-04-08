from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import RoleEnum, User, WebUser
from app.services.email import EmailService
from app.web.auth import hash_password
from app.web.deps import get_current_user, get_db, require_admin

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/users", tags=["users"])

WEB_ROLES = [
    ("superadmin", "Суперадмин"),
    ("admin", "Администратор"),
    ("manager", "Менеджер ПВЗ"),
    ("senior", "Управляющий ПВЗ"),
    ("employee", "Сотрудник"),
    ("disputes", "Менеджер оспариваний"),
    ("marketing", "Маркетолог"),
    ("viewer", "Просмотр"),
]

ROLE_LABELS = dict(WEB_ROLES)

SORT_OPTIONS = [
    ("id", "ID"),
    ("login", "Логин"),
    ("full_name", "ФИО"),
    ("is_active", "Статус"),
    ("last_login_at", "Последний вход"),
    ("created_at", "Дата создания"),
]


def _parse_sort(sort_by: str, sort_dir: str) -> tuple[str, str]:
    valid_fields = {name for name, _ in SORT_OPTIONS}
    normalized_field = sort_by if sort_by in valid_fields else "full_name"
    normalized_dir = "desc" if sort_dir == "desc" else "asc"
    return normalized_field, normalized_dir


def _sort_expression(sort_by: str, sort_dir: str):
    field_map = {
        "id": WebUser.id,
        "login": WebUser.login,
        "full_name": WebUser.full_name,
        "is_active": WebUser.is_active,
        "last_login_at": WebUser.last_login_at,
        "created_at": WebUser.created_at,
    }
    col = field_map.get(sort_by, WebUser.full_name)
    primary = desc(col) if sort_dir == "desc" else asc(col)
    return primary, asc(WebUser.id)


def _parse_roles(form) -> list[str]:
    """Extract selected roles from form checkboxes (name='roles')."""
    roles = form.getlist("roles")
    valid = {code for code, _ in WEB_ROLES}
    cleaned = [r for r in roles if r in valid]
    return cleaned if cleaned else ["viewer"]


@router.get("", response_class=HTMLResponse)
async def list_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_admin),
    search: str = "",
    role: str = "",
    sort_by: str = "full_name",
    sort_dir: str = "asc",
    page: int = 1,
    notice: str = "",
    error: str = "",
):
    per_page = 25
    query = select(WebUser)
    sort_by, sort_dir = _parse_sort(sort_by, sort_dir)

    if search:
        query = query.where(
            WebUser.full_name.ilike(f"%{search}%") | WebUser.login.ilike(f"%{search}%")
        )
    if role:
        # substring match on the JSON array text
        query = query.where(WebUser.roles_json.contains(role))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    order_primary, order_secondary = _sort_expression(sort_by, sort_dir)
    query = query.order_by(order_primary, order_secondary).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    users = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(request, "users/list.html", {
        "current_user": current_user,
        "active_page": "users",
        "items": users,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "search": search,
        "role": role,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "sort_options": SORT_OPTIONS,
        "notice": notice,
        "error": error,
        "web_roles": WEB_ROLES,
        "role_labels": ROLE_LABELS,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_user(
    request: Request,
    current_user: WebUser = Depends(require_admin),
):
    return templates.TemplateResponse(request, "users/form.html", {
        "current_user": current_user,
        "active_page": "users",
        "item": None,
        "web_roles": WEB_ROLES,
        "employees": [],
        "linked_employee": None,
        "error": None,
    })


@router.post("/new")
async def create_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_admin),
):
    form = await request.form()
    login = str(form.get("login", "")).strip()
    password = str(form.get("password", ""))

    if not login or not password:
        return templates.TemplateResponse(request, "users/form.html", {
            "current_user": current_user,
            "active_page": "users",
            "item": None,
            "web_roles": WEB_ROLES,
            "employees": [],
            "linked_employee": None,
            "error": "Логин и пароль обязательны",
        })

    existing = await db.execute(select(WebUser).where(WebUser.login == login))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse(request, "users/form.html", {
            "current_user": current_user,
            "active_page": "users",
            "item": None,
            "web_roles": WEB_ROLES,
            "employees": [],
            "linked_employee": None,
            "error": "Пользователь с таким логином уже существует",
        })

    roles = _parse_roles(form)

    email_svc = EmailService(get_settings())
    if email_svc.enabled and current_user.email:
        payload = {
            "login": login,
            "password_hash": hash_password(password),
            "full_name": str(form.get("full_name", "")).strip() or login,
            "phone": str(form.get("phone", "")).strip() or None,
            "email": str(form.get("email", "")).strip() or None,
            "roles": roles,
            "is_active": form.get("is_active") == "on",
        }
        await email_svc.send_confirmation_code(
            db, current_user.id, current_user.email,
            "user_create", json.dumps(payload),
        )
        return RedirectResponse(url="/confirm/verify?operation=user_create", status_code=302)

    user = WebUser(
        login=login,
        password_hash=hash_password(password),
        full_name=str(form.get("full_name", "")).strip() or login,
        phone=str(form.get("phone", "")).strip() or None,
        email=str(form.get("email", "")).strip() or None,
        roles_json=json.dumps(roles),
        is_active=form.get("is_active") == "on",
    )
    db.add(user)
    await db.commit()
    return RedirectResponse(url="/users", status_code=302)


@router.get("/{user_id}/edit", response_class=HTMLResponse)
async def edit_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_admin),
):
    result = await db.execute(select(WebUser).where(WebUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/users", status_code=302)

    employees = (await db.execute(select(User).order_by(User.full_name))).scalars().all()
    linked_employee = None
    if user.user_id:
        linked_employee = (await db.execute(select(User).where(User.id == user.user_id))).scalar_one_or_none()

    return templates.TemplateResponse(request, "users/form.html", {
        "current_user": current_user,
        "active_page": "users",
        "item": user,
        "web_roles": WEB_ROLES,
        "employees": employees,
        "linked_employee": linked_employee,
        "error": None,
    })


@router.post("/{user_id}/edit")
async def update_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_admin),
):
    result = await db.execute(select(WebUser).where(WebUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/users", status_code=302)

    form = await request.form()
    new_roles = _parse_roles(form)
    new_is_active = form.get("is_active") == "on"
    new_password = str(form.get("password", "")).strip()

    roles_changed = set(new_roles) != set(user.roles)
    deactivated = user.is_active and not new_is_active

    email_svc = EmailService(get_settings())
    if (roles_changed or deactivated) and email_svc.enabled and current_user.email:
        payload = {
            "user_id": user_id,
            "full_name": str(form.get("full_name", "")).strip() or user.full_name,
            "phone": str(form.get("phone", "")).strip() or None,
            "email": str(form.get("email", "")).strip() or None,
            "roles": new_roles,
            "is_active": new_is_active,
            "password_hash": hash_password(new_password) if new_password else None,
        }
        await email_svc.send_confirmation_code(
            db, current_user.id, current_user.email,
            "user_edit_role", json.dumps(payload),
        )
        return RedirectResponse(url="/confirm/verify?operation=user_edit_role", status_code=302)

    user.full_name = str(form.get("full_name", "")).strip() or user.full_name
    user.phone = str(form.get("phone", "")).strip() or None
    user.email = str(form.get("email", "")).strip() or None
    user.roles_json = json.dumps(new_roles)
    user.is_active = new_is_active
    if new_password:
        user.password_hash = hash_password(new_password)
    raw_emp_id = str(form.get("employee_id", "")).strip()
    new_emp_id = int(raw_emp_id) if raw_emp_id.isdigit() else None
    user.user_id = new_emp_id

    # Update telegram_id on the linked employee
    raw_tg_id = str(form.get("telegram_id", "")).strip()
    if new_emp_id and raw_tg_id.lstrip("-").isdigit():
        new_tg_id = int(raw_tg_id)
        employee = (await db.execute(select(User).where(User.id == new_emp_id))).scalar_one_or_none()
        if employee and employee.telegram_id != new_tg_id:
            # Make sure the new ID isn't taken by another employee
            conflict = (await db.execute(
                select(User).where(User.telegram_id == new_tg_id, User.id != new_emp_id)
            )).scalar_one_or_none()
            if not conflict:
                employee.telegram_id = new_tg_id

    await db.commit()
    return RedirectResponse(url="/users", status_code=302)


@router.post("/{user_id}/create-employee")
async def create_employee_from_web_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_admin),
):
    """Create a bot-side User (employee) record from a web user."""
    web_user = (await db.execute(select(WebUser).where(WebUser.id == user_id))).scalar_one_or_none()
    if not web_user:
        return RedirectResponse(url="/users", status_code=302)

    form = await request.form()
    full_name = str(form.get("full_name", "")).strip() or web_user.full_name
    phone = str(form.get("phone", "")).strip() or web_user.phone or None
    role_raw = str(form.get("role", "employee")).strip()
    role = RoleEnum.ADMIN if role_raw == "admin" else RoleEnum.EMPLOYEE

    tg_raw = str(form.get("telegram_id", "")).strip()
    if tg_raw.lstrip("-").isdigit():
        telegram_id = int(tg_raw)
    else:
        # Placeholder: large negative number based on web user id, won't conflict with Telegram IDs
        telegram_id = -(1_000_000_000 + user_id)

    # Check uniqueness
    existing = (await db.execute(
        select(User).where(User.telegram_id == telegram_id)
    )).scalar_one_or_none()
    if existing:
        return RedirectResponse(url="/users", status_code=302)

    employee = User(
        telegram_id=telegram_id,
        full_name=full_name,
        phone=phone,
        role=role,
        is_active=True,
    )
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return RedirectResponse(url=f"/employees/{employee.id}", status_code=302)


@router.post("/{user_id}/delete")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_admin),
):
    user = (await db.execute(select(WebUser).where(WebUser.id == user_id))).scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/users?error=not_found", status_code=302)

    if user.id == current_user.id:
        return RedirectResponse(url="/users?error=cannot_delete_self", status_code=302)

    if "superadmin" in user.roles:
        active_superadmins = (
            await db.execute(
                select(func.count())
                .select_from(WebUser)
                .where(
                    WebUser.is_active.is_(True),
                    WebUser.roles_json.contains("superadmin"),
                )
            )
        ).scalar() or 0
        if active_superadmins <= 1:
            return RedirectResponse(url="/users?error=last_superadmin", status_code=302)

    await db.delete(user)
    await db.commit()
    return RedirectResponse(url="/users?notice=deleted", status_code=302)
