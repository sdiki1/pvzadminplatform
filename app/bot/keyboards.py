from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.db.models import Point


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


# ---------------------------------------------------------------------------
# Main employee menu — just two actions
# ---------------------------------------------------------------------------

MAIN_MENU = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            _btn("🟢 Начать смену", "shift:open"),
            _btn("🔴 Закрыть смену", "shift:close"),
        ],
    ]
)


# ---------------------------------------------------------------------------
# Shift open — pick a point from today's planned shifts
# ---------------------------------------------------------------------------

def shift_open_points_keyboard(planned_shifts, points_map: dict) -> InlineKeyboardMarkup:
    rows = []
    for ps in planned_shifts:
        point = points_map.get(ps.point_id)
        name = point.name if point else f"Точка #{ps.point_id}"
        time_str = ""
        if ps.start_time and ps.end_time:
            time_str = f"  {ps.start_time:%H:%M}–{ps.end_time:%H:%M}"
        rows.append([_btn(f"📍 {name}{time_str}", f"openpoint:{ps.point_id}")])
    rows.append([_btn("❌ Отмена", "shift:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Location (Telegram requires ReplyKeyboard for location sharing)
# ---------------------------------------------------------------------------

def request_location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


# ---------------------------------------------------------------------------
# Geofence approval — sent to admins
# ---------------------------------------------------------------------------

def geofence_approve_keyboard(exception_id: int, shift_id: int, event: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("✅ Подтвердить", f"geoapprove:{exception_id}:{shift_id}:{event}:ok"),
                _btn("❌ Отклонить", f"geoapprove:{exception_id}:{shift_id}:{event}:reject"),
            ]
        ]
    )


# ---------------------------------------------------------------------------
# Legacy stubs used by admin.py commands (expense flow, etc.)
# ---------------------------------------------------------------------------

def points_keyboard(points: list[Point], action: str) -> InlineKeyboardMarkup:
    rows = [[_btn(f"📍 {p.name}", f"{action}:{p.id}")] for p in points]
    rows.append([_btn("❌ Отмена", "shift:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def critical_confirm_keyboard(action_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("✅ Подтвердить действие", f"critical:{action_id}")]]
    )


def tomorrow_confirm_keyboard(target_date: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            _btn("✅ Да", f"confirm:{target_date}:yes"),
            _btn("❌ Нет", f"confirm:{target_date}:no"),
            _btn("🤷 Не знаю", f"confirm:{target_date}:unknown"),
        ]]
    )
