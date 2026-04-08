from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import notify
from app.bot.context import ensure_actor
from app.bot.keyboards import (
    MAIN_MENU,
    geofence_approve_keyboard,
    remove_keyboard,
    request_location_keyboard,
    shift_open_points_keyboard,
)
from app.bot.states import CloseShiftState, OpenShiftState
from app.config import get_settings
from app.db.models import ApprovalStatus, GeoStatus, PlannedShift, RoleEnum
from app.db.repositories import (
    GeofenceExceptionRepo,
    PointRepo,
    ShiftRepo,
    UserRepo,
)
from app.db.session import SessionLocal
from app.services.geofence import GeofenceService
from sqlalchemy import select

router = Router(name="employee")
settings = get_settings()
TZ = ZoneInfo(settings.timezone)


# ---------------------------------------------------------------------------
# /start  — show main menu
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with SessionLocal() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_tg_id(message.from_user.id)

        if not user and message.from_user.id in settings.admin_ids:
            full_name = " ".join(filter(None, [
                message.from_user.last_name,
                message.from_user.first_name,
            ]))
            user = await user_repo.create_or_update(
                telegram_id=message.from_user.id,
                full_name=full_name or str(message.from_user.id),
                role=RoleEnum.ADMIN,
            )

    if not user:
        await message.answer(
            "👋 Вы не зарегистрированы.\n"
            f"Передайте администратору ваш Telegram ID: <code>{message.from_user.id}</code>"
        )
        return

    if not user.is_active:
        await message.answer("⛔️ Аккаунт деактивирован. Обратитесь к администратору.")
        return

    await message.answer(
        f"👋 Привет, <b>{user.full_name.split()[0]}</b>!",
        reply_markup=MAIN_MENU,
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("📋 Меню", reply_markup=MAIN_MENU)


# ---------------------------------------------------------------------------
# Cancel any FSM
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "shift:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Отменено", reply_markup=None)
    await callback.message.answer("📋 Меню", reply_markup=MAIN_MENU)
    await callback.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Действие отменено", reply_markup=remove_keyboard())
    await message.answer("📋 Меню", reply_markup=MAIN_MENU)


# ---------------------------------------------------------------------------
# Open shift
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "shift:open")
async def cb_shift_open(callback: CallbackQuery, state: FSMContext) -> None:
    async with SessionLocal() as session:
        actor = await ensure_actor(callback, session)
        if not actor:
            return

        shift_repo = ShiftRepo(session)
        if await shift_repo.get_open_shift(actor.id):
            await callback.answer("⚠️ У вас уже есть открытая смена!", show_alert=True)
            return

        today = datetime.now(TZ).date()
        today_planned = (await session.execute(
            select(PlannedShift).where(
                PlannedShift.user_id == actor.id,
                PlannedShift.shift_date == today,
            )
        )).scalars().all()

        if not today_planned:
            await callback.answer(
                "На сегодня нет запланированных смен.\nОбратитесь к администратору.",
                show_alert=True,
            )
            return

        point_repo = PointRepo(session)
        points_map = {p.id: p for p in await point_repo.list_all()}

    await state.set_state(OpenShiftState.waiting_point)
    await callback.message.edit_text(
        "🟢 <b>Открыть смену</b>\n\nВыберите точку:",
        reply_markup=shift_open_points_keyboard(today_planned, points_map),
    )
    await callback.answer()


@router.callback_query(OpenShiftState.waiting_point, F.data.startswith("openpoint:"))
async def cb_open_point_selected(callback: CallbackQuery, state: FSMContext) -> None:
    point_id = int(callback.data.split(":")[1])
    await state.update_data(point_id=point_id)
    await state.set_state(OpenShiftState.waiting_location)
    await callback.message.edit_text(
        "📍 <b>Геолокация</b>\n\nОтправьте местоположение для открытия смены.",
        reply_markup=None,
    )
    await callback.message.answer(
        "👇 Нажмите кнопку ниже:",
        reply_markup=request_location_keyboard(),
    )
    await callback.answer()


@router.message(OpenShiftState.waiting_location, F.location)
async def fsm_open_location(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    point_id = data.get("point_id")
    if not point_id:
        await state.clear()
        await message.answer("⚠️ Ошибка. Начните заново.", reply_markup=remove_keyboard())
        return

    async with SessionLocal() as session:
        actor = await ensure_actor(message, session)
        if not actor:
            await state.clear()
            return

        # Проверяем плановую смену ещё раз
        today = datetime.now(TZ).date()
        planned = (await session.execute(
            select(PlannedShift).where(
                PlannedShift.user_id == actor.id,
                PlannedShift.shift_date == today,
                PlannedShift.point_id == point_id,
            )
        )).scalar_one_or_none()
        if not planned:
            await state.clear()
            await message.answer("❌ Плановая смена не найдена.", reply_markup=remove_keyboard())
            await message.answer("📋 Меню", reply_markup=MAIN_MENU)
            return

        point_repo = PointRepo(session)
        point = await point_repo.get_by_id(point_id)
        if not point:
            await state.clear()
            await message.answer("❌ Точка не найдена.", reply_markup=remove_keyboard())
            return

        geo = GeofenceService.check(point, message.location.latitude, message.location.longitude)
        approval = ApprovalStatus.APPROVED if geo.status == GeoStatus.OK else ApprovalStatus.PENDING

        shift_repo = ShiftRepo(session)
        opened_at = datetime.now(TZ).replace(tzinfo=None)
        shift = await shift_repo.create_open_shift(
            user_id=actor.id,
            point_id=point.id,
            shift_date=opened_at.date(),
            opened_at=opened_at,
            open_lat=message.location.latitude,
            open_lon=message.location.longitude,
            open_distance_m=geo.distance_m,
            open_geo_status=geo.status,
            open_approval_status=approval,
        )

        if geo.status == GeoStatus.OUTSIDE:
            ge_repo = GeofenceExceptionRepo(session)
            ge = await ge_repo.create(shift.id, "open", geo.distance_m)
            await notify.notify_admins(
                f"⚠️ <b>Отклонение геолокации при открытии</b>\n\n"
                f"👤 {actor.full_name}\n"
                f"📍 {point.name}\n"
                f"📏 {geo.distance_m:.0f} м от точки",
                reply_markup=geofence_approve_keyboard(ge.id, shift.id, "open"),
            )

    await state.clear()
    geo_line = "✅ геолокация подтверждена" if geo.status == GeoStatus.OK else f"⚠️ геолокация вне радиуса ({geo.distance_m:.0f} м) — на проверке"
    await message.answer(
        f"🟢 <b>Смена открыта!</b>\n\n"
        f"📍 {point.name}\n"
        f"⏰ {opened_at:%H:%M}\n"
        f"{geo_line}",
        reply_markup=remove_keyboard(),
    )
    await message.answer("📋 Меню", reply_markup=MAIN_MENU)

    # Уведомляем администраторов
    await notify.notify_shift_opened(
        employee_name=actor.full_name,
        point_name=point.name,
        opened_at_str=f"{opened_at:%H:%M}",
        geo_ok=(geo.status == GeoStatus.OK),
    )


# ---------------------------------------------------------------------------
# Close shift
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "shift:close")
async def cb_shift_close(callback: CallbackQuery, state: FSMContext) -> None:
    async with SessionLocal() as session:
        actor = await ensure_actor(callback, session)
        if not actor:
            return

        shift_repo = ShiftRepo(session)
        shift = await shift_repo.get_open_shift(actor.id)
        if not shift:
            await callback.answer("⚠️ Нет открытой смены.", show_alert=True)
            return

        point_repo = PointRepo(session)
        point = await point_repo.get_by_id(shift.point_id)

    await state.set_state(CloseShiftState.waiting_location)
    await state.update_data(shift_id=shift.id)
    await callback.message.edit_text(
        f"🔴 <b>Закрыть смену</b>\n\n"
        f"📍 {point.name if point else '—'}\n"
        f"⏰ Открыта с {shift.opened_at:%H:%M}\n\n"
        "Отправьте геолокацию для закрытия.",
        reply_markup=None,
    )
    await callback.message.answer(
        "👇 Нажмите кнопку ниже:",
        reply_markup=request_location_keyboard(),
    )
    await callback.answer()


@router.message(CloseShiftState.waiting_location, F.location)
async def fsm_close_location(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    shift_id = data.get("shift_id")
    if not shift_id:
        await state.clear()
        await message.answer("⚠️ Ошибка. Начните заново.", reply_markup=remove_keyboard())
        return

    async with SessionLocal() as session:
        actor = await ensure_actor(message, session)
        if not actor:
            await state.clear()
            return

        shift_repo = ShiftRepo(session)
        ge_repo = GeofenceExceptionRepo(session)
        point_repo = PointRepo(session)

        shift = await shift_repo.get_by_id(shift_id)
        if not shift or shift.user_id != actor.id:
            await state.clear()
            await message.answer("❌ Смена не найдена.", reply_markup=remove_keyboard())
            return

        point = await point_repo.get_by_id(shift.point_id)
        if not point:
            await state.clear()
            await message.answer("❌ Точка не найдена.", reply_markup=remove_keyboard())
            return

        geo = GeofenceService.check(point, message.location.latitude, message.location.longitude)
        approval = ApprovalStatus.APPROVED if geo.status == GeoStatus.OK else ApprovalStatus.PENDING
        closed_at = datetime.now(TZ).replace(tzinfo=None)

        shift = await shift_repo.close_shift(
            shift=shift,
            closed_at=closed_at,
            close_lat=message.location.latitude,
            close_lon=message.location.longitude,
            close_distance_m=geo.distance_m,
            close_geo_status=geo.status,
            close_approval_status=approval,
        )

        if geo.status == GeoStatus.OUTSIDE:
            ge = await ge_repo.create(shift.id, "close", geo.distance_m)
            await notify.notify_admins(
                f"⚠️ <b>Отклонение геолокации при закрытии</b>\n\n"
                f"👤 {actor.full_name}\n"
                f"📍 {point.name}\n"
                f"📏 {geo.distance_m:.0f} м от точки",
                reply_markup=geofence_approve_keyboard(ge.id, shift.id, "close"),
            )

    await state.clear()
    dur = shift.duration_minutes or 0
    hours, mins = dur // 60, dur % 60
    dur_str = f"{hours}ч {mins}мин" if hours else f"{mins}мин"
    geo_line = "✅ геолокация подтверждена" if geo.status == GeoStatus.OK else f"⚠️ геолокация вне радиуса ({geo.distance_m:.0f} м)"
    await message.answer(
        f"⚫️ <b>Смена закрыта!</b>\n\n"
        f"📍 {point.name}\n"
        f"⏰ {shift.opened_at:%H:%M} — {closed_at:%H:%M} ({dur_str})\n"
        f"{geo_line}",
        reply_markup=remove_keyboard(),
    )
    await message.answer("📋 Меню", reply_markup=MAIN_MENU)

    # Уведомляем администраторов
    await notify.notify_shift_closed(
        employee_name=actor.full_name,
        point_name=point.name,
        opened_at_str=f"{shift.opened_at:%H:%M}",
        closed_at_str=f"{closed_at:%H:%M}",
        duration_minutes=dur,
        geo_ok=(geo.status == GeoStatus.OK),
    )


# ---------------------------------------------------------------------------
# Geofence approval — admins press Подтвердить / Отклонить in notifications
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("geoapprove:"))
async def cb_geoapprove(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    _, exc_id_raw, shift_id_raw, event, decision = parts
    try:
        exc_id = int(exc_id_raw)
        shift_id = int(shift_id_raw)
    except ValueError:
        await callback.answer("Некорректный id", show_alert=True)
        return

    status = ApprovalStatus.APPROVED if decision == "ok" else ApprovalStatus.REJECTED

    async with SessionLocal() as session:
        actor = await ensure_actor(callback, session)
        if not actor:
            return

        ge_repo = GeofenceExceptionRepo(session)
        shift_repo = ShiftRepo(session)
        user_repo = UserRepo(session)

        await ge_repo.set_status(exc_id, status, reviewed_by=actor.id)
        if event == "open":
            await shift_repo.update_open_approval(shift_id, status)
        else:
            await shift_repo.update_close_approval(shift_id, status)

        shift = await shift_repo.get_by_id(shift_id)
        if shift:
            employee = await user_repo.get_by_id(shift.user_id)
            if employee:
                try:
                    word = "подтвердил ✅" if status == ApprovalStatus.APPROVED else "отклонил ❌"
                    await callback.bot.send_message(
                        employee.telegram_id,
                        f"👤 Администратор {word} геолокацию по вашей смене.",
                    )
                except Exception:
                    pass

    icon = "✅" if status == ApprovalStatus.APPROVED else "❌"
    await callback.answer(f"{icon} Решение сохранено", show_alert=True)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

