from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WebRoleEnum, WebUser
from app.web.auth import hash_password
from app.web.deps import get_current_user, get_db, require_admin

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/users", tags=["users"])

WEB_ROLES = [
    ("superadmin", "Суперадмин"),
    ("admin", "Администратор"),
    ("manager", "Руководитель"),
    ("senior", "Старший ПВЗ"),
    ("employee", "Сотрудник"),
    ("disputes", "Менеджер оспариваний"),
    ("marketing", "Маркетолог"),
    ("viewer", "Просмотр"),
]


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
        query = query.where(WebUser.full_name.ilike(f"%{search}%") | WebUser.login.ilike(f"%{search}%"))
    if role:
        query = query.where(WebUser.role == role)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(WebUser.full_name).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    users = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse("users/list.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "users",
        "items": users,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "search": search,
        "role": role,
        "web_roles": WEB_ROLES,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_user(
    request: Request,
    current_user: WebUser = Depends(require_admin),
):
    return templates.TemplateResponse("users/form.html", {
        "request": request,
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
    login = form.get("login", "").strip()
    password = form.get("password", "")

    if not login or not password:
        return templates.TemplateResponse("users/form.html", {
            "request": request,
            "current_user": current_user,
            "active_page": "users",
            "item": None,
            "web_roles": WEB_ROLES,
            "error": "Логин и пароль обязательны",
        })

    # Check if login already exists
    existing = await db.execute(select(WebUser).where(WebUser.login == login))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse("users/form.html", {
            "request": request,
            "current_user": current_user,
            "active_page": "users",
            "item": None,
            "web_roles": WEB_ROLES,
            "error": "Пользователь с таким логином уже существует",
        })

    user = WebUser(
        login=login,
        password_hash=hash_password(password),
        full_name=form.get("full_name", "").strip() or login,
        phone=form.get("phone", "").strip() or None,
        email=form.get("email", "").strip() or None,
        role=form.get("role", "viewer"),
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

    return templates.TemplateResponse("users/form.html", {
        "request": request,
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
    user.full_name = form.get("full_name", "").strip() or user.login
    user.phone = form.get("phone", "").strip() or None
    user.email = form.get("email", "").strip() or None
    user.role = form.get("role", "viewer")
    user.is_active = form.get("is_active") == "on"

    # Update password only if provided
    new_password = form.get("password", "").strip()
    if new_password:
        user.password_hash = hash_password(new_password)

    await db.commit()
    return RedirectResponse(url="/users", status_code=302)
