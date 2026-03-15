from __future__ import annotations

from typing import Optional

from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RoleEnum, User
from app.db.repositories import UserRepo


async def resolve_actor(event: Message | CallbackQuery, session: AsyncSession) -> Optional[User]:
    tg_id = event.from_user.id
    user_repo = UserRepo(session)
    return await user_repo.get_by_tg_id(tg_id)


async def ensure_actor(event: Message | CallbackQuery, session: AsyncSession) -> Optional[User]:
    user = await resolve_actor(event, session)
    if user:
        return user

    text = (
        "Ваш аккаунт не зарегистрирован в системе. "
        "Обратитесь к администратору, чтобы он добавил вас через /admin_add_user."
    )
    if isinstance(event, Message):
        await event.answer(text)
    else:
        await event.message.answer(text)
    return None


def is_admin(user: User) -> bool:
    return user.role == RoleEnum.ADMIN
