"""Notification service for Telegram bot.

Call `set_bot(bot)` once at startup, then use `notify_admins()` and
the domain-specific helpers from anywhere in the application.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot

log = logging.getLogger("pvz.notify")

_bot: "Bot | None" = None
_admin_ids: list[int] = []


def set_bot(bot: "Bot") -> None:
    global _bot
    _bot = bot


def set_admin_ids(ids: list[int]) -> None:
    """Called at startup with admin telegram IDs from settings + DB."""
    global _admin_ids
    _admin_ids = list(ids)


async def notify_admins(text: str, **kwargs) -> None:
    """Send *text* to every admin telegram ID. Silently skips failures."""
    if not _bot or not _admin_ids:
        return
    for tg_id in _admin_ids:
        try:
            await _bot.send_message(tg_id, text, parse_mode="HTML", **kwargs)
        except Exception as exc:
            log.debug("notify_admins: failed to send to %s: %s", tg_id, exc)


# ---------------------------------------------------------------------------
# Domain notifications
# ---------------------------------------------------------------------------

async def notify_shift_opened(
    employee_name: str,
    point_name: str,
    opened_at_str: str,
    geo_ok: bool,
) -> None:
    geo_label = "✅ геолокация ОК" if geo_ok else "⚠️ геолокация вне радиуса — требует проверки"
    await notify_admins(
        f"🟢 <b>Смена открыта</b>\n\n"
        f"👤 {employee_name}\n"
        f"📍 {point_name}\n"
        f"⏰ {opened_at_str}\n"
        f"{geo_label}"
    )


async def notify_shift_closed(
    employee_name: str,
    point_name: str,
    opened_at_str: str,
    closed_at_str: str,
    duration_minutes: int,
    geo_ok: bool,
) -> None:
    hours = duration_minutes // 60
    mins = duration_minutes % 60
    dur_str = f"{hours}ч {mins}мин" if hours else f"{mins}мин"
    geo_label = "✅ геолокация ОК" if geo_ok else "⚠️ геолокация вне радиуса"
    await notify_admins(
        f"⚫️ <b>Смена закрыта</b>\n\n"
        f"👤 {employee_name}\n"
        f"📍 {point_name}\n"
        f"⏰ {opened_at_str} — {closed_at_str} ({dur_str})\n"
        f"{geo_label}"
    )


async def notify_tardiness(
    employee_name: str,
    point_name: str,
    shift_date_str: str,
    delay_minutes: int,
    fine_amount: int,
) -> None:
    await notify_admins(
        f"⏰ <b>Опоздание</b>\n\n"
        f"👤 {employee_name}\n"
        f"📍 {point_name}\n"
        f"📅 {shift_date_str}\n"
        f"🕐 Опоздание: {delay_minutes} мин\n"
        f"💸 Штраф: {fine_amount} ₽"
    )


async def notify_appeal_created(
    point_name: str,
    appeal_type: str,
    barcode: str | None,
    ticket: str | None,
    amount: str | None,
    created_by: str,
) -> None:
    parts = [
        f"📋 <b>Новое оспаривание</b>\n",
        f"📍 Точка: {point_name}",
        f"📌 Тип: {appeal_type}",
    ]
    if barcode:
        parts.append(f"🏷 Штрихкод: {barcode}")
    if ticket:
        parts.append(f"🎫 Тикет: {ticket}")
    if amount:
        parts.append(f"💰 Сумма: {amount} ₽")
    parts.append(f"👤 Создал: {created_by}")
    await notify_admins("\n".join(parts))


async def notify_appeal_status_changed(
    point_name: str,
    appeal_id: int,
    old_status: str,
    new_status: str,
    changed_by: str,
) -> None:
    status_icons = {
        "none": "⬜️",
        "in_progress": "🔄",
        "appealed": "⚖️",
        "not_appealed": "❌",
        "closed": "✅",
    }
    old_icon = status_icons.get(old_status, "❓")
    new_icon = status_icons.get(new_status, "❓")
    await notify_admins(
        f"🔔 <b>Оспаривание #{appeal_id} обновлено</b>\n\n"
        f"📍 {point_name}\n"
        f"{old_icon} {old_status} → {new_icon} {new_status}\n"
        f"👤 {changed_by}"
    )
