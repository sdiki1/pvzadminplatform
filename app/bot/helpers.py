from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.repositories import UserRepo


def parse_decimal(text: str) -> Decimal:
    text = text.strip().replace(" ", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Неверное число: {text}") from exc


def parse_date_iso(text: str) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError as exc:
        raise ValueError(f"Неверная дата: {text}. Нужен формат YYYY-MM-DD") from exc


async def admin_telegram_ids(session: AsyncSession, settings: Settings) -> list[int]:
    user_repo = UserRepo(session)
    admins = await user_repo.list_admins()
    ids = {u.telegram_id for u in admins}
    ids.update(settings.admin_ids)
    return sorted(ids)
