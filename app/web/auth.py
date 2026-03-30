from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import WebUser
from app.db.session import SessionLocal

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["auth"])


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.web_secret_key, algorithm=settings.jwt_algorithm)


async def authenticate_user(session: AsyncSession, login: str, password: str) -> Optional[WebUser]:
    result = await session.execute(
        select(WebUser).where(WebUser.login == login, WebUser.is_active == True)
    )
    user = result.scalar_one_or_none()
    if user and verify_password(password, user.password_hash):
        user.last_login_at = datetime.utcnow()
        await session.commit()
        return user
    return None


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html", {"error": None})


@router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    login = form.get("login", "").strip()
    password = form.get("password", "")

    async with SessionLocal() as db:
        user = await authenticate_user(db, login, password)

    if not user:
        return templates.TemplateResponse(
            request, "auth/login.html",
            {"error": "Неверный логин или пароль"},
            status_code=401,
        )

    token = create_access_token(data={"sub": str(user.id), "role": user.role})
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=get_settings().jwt_expire_minutes * 60,
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response
