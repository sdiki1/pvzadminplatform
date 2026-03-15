from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.db.models import Point, RoleEnum


EMPLOYEE_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Подтвердить выход на завтра")],
        [KeyboardButton(text="Открыть смену"), KeyboardButton(text="Закрыть смену")],
        [KeyboardButton(text="Мои смены"), KeyboardButton(text="Моя ЗП")],
    ],
    resize_keyboard=True,
)

ADMIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Подтвердить выход на завтра")],
        [KeyboardButton(text="Открыть смену"), KeyboardButton(text="Закрыть смену")],
        [KeyboardButton(text="Мои смены"), KeyboardButton(text="Моя ЗП")],
        [KeyboardButton(text="Админ: управление")],
        [KeyboardButton(text="Админ: отчеты"), KeyboardButton(text="Админ: синхронизация")],
        [KeyboardButton(text="Админ: расходы"), KeyboardButton(text="Админ: расчет ЗП")],
    ],
    resize_keyboard=True,
)


def menu_for_role(role: RoleEnum) -> ReplyKeyboardMarkup:
    if role == RoleEnum.ADMIN:
        return ADMIN_MENU
    return EMPLOYEE_MENU


def tomorrow_confirm_keyboard(target_date: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"confirm:{target_date}:yes"),
                InlineKeyboardButton(text="Нет", callback_data=f"confirm:{target_date}:no"),
                InlineKeyboardButton(text="Не знаю", callback_data=f"confirm:{target_date}:unknown"),
            ]
        ]
    )


def points_keyboard(points: list[Point], action: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in points:
        rows.append([InlineKeyboardButton(text=f"{p.name} ({p.address})", callback_data=f"{action}:{p.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def request_location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить геолокацию", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def geofence_approve_keyboard(exception_id: int, shift_id: int, event: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить", callback_data=f"geoapprove:{exception_id}:{shift_id}:{event}:ok"
                ),
                InlineKeyboardButton(
                    text="Отклонить", callback_data=f"geoapprove:{exception_id}:{shift_id}:{event}:reject"
                ),
            ]
        ]
    )


def critical_confirm_keyboard(action_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подтвердить действие", callback_data=f"critical:{action_id}")],
        ]
    )
