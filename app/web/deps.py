from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Optional

from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import WebRoleEnum, WebUser
from app.db.session import SessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


def _get_token_from_cookie(request: Request) -> Optional[str]:
    return request.cookies.get("access_token")


def _decode_token(token: str) -> Optional[dict]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.web_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[WebUser]:
    token = _get_token_from_cookie(request)
    if not token:
        return None
    payload = _decode_token(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    result = await db.execute(
        select(WebUser).where(WebUser.id == int(user_id), WebUser.is_active == True)
    )
    return result.scalar_one_or_none()


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebUser:
    user = await get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


class RequireRole:
    def __init__(self, *allowed_roles: WebRoleEnum):
        self.allowed_values = {r.value for r in allowed_roles}

    async def __call__(self, user: WebUser = Depends(get_current_user)) -> WebUser:
        if not set(user.roles).intersection(self.allowed_values):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user


require_admin = RequireRole(WebRoleEnum.SUPERADMIN, WebRoleEnum.ADMIN)
require_manager = RequireRole(
    WebRoleEnum.SUPERADMIN, WebRoleEnum.ADMIN, WebRoleEnum.MANAGER, WebRoleEnum.SENIOR
)
