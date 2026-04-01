from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WebUser
from app.web.auth import hash_password, verify_password
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(
    request: Request,
    current_user: WebUser = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "profile/change_password.html", {
        "current_user": current_user,
        "active_page": None,
        "error": None,
        "success": False,
    })


@router.post("/change-password")
async def change_password_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()
    current_pw = str(form.get("current_password", ""))
    new_pw = str(form.get("new_password", ""))
    confirm_pw = str(form.get("confirm_password", ""))

    def err(msg: str):
        return templates.TemplateResponse(request, "profile/change_password.html", {
            "current_user": current_user,
            "active_page": None,
            "error": msg,
            "success": False,
        })

    if not verify_password(current_pw, current_user.password_hash):
        return err("Неверный текущий пароль")

    if len(new_pw) < 6:
        return err("Новый пароль должен содержать минимум 6 символов")

    if new_pw != confirm_pw:
        return err("Пароли не совпадают")

    # Re-fetch within this session to allow update
    user = (await db.execute(select(WebUser).where(WebUser.id == current_user.id))).scalar_one()
    user.password_hash = hash_password(new_pw)
    await db.commit()

    return templates.TemplateResponse(request, "profile/change_password.html", {
        "current_user": current_user,
        "active_page": None,
        "error": None,
        "success": True,
    })
