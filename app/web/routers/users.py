from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
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
    page: int = 1,
):
    per_page = 25
    query = select(WebUser)

    if search:
        query = query.where(
            WebUser.full_name.ilike(f"%{search}%") | WebUser.login.ilike(f"%{search}%")
        )
    if role:
        # substring match on the JSON array text
        query = query.where(WebUser.roles_json.contains(role))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(WebUser.full_name).offset((page - 1) * per_page).limit(per_page)
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
            "error": "Логин и пароль обязательны",
        })

    existing = await db.execute(select(WebUser).where(WebUser.login == login))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse(request, "users/form.html", {
            "current_user": current_user,
            "active_page": "users",
            "item": None,
            "web_roles": WEB_ROLES,
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

    return templates.TemplateResponse(request, "users/form.html", {
        "current_user": current_user,
        "active_page": "users",
        "item": user,
        "web_roles": WEB_ROLES,
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
