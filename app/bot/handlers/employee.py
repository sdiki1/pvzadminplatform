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
    shift_open_points_keyboard,
)
from app.bot.states import OpenShiftState
from app.config import get_settings
from app.db.models import ApprovalStatus, GeoStatus, PlannedShift, Point, RoleEnum
from app.db.repositories import PointRepo, ShiftRepo, UserRepo
from app.db.session import SessionLocal
from app.services.email import EmailService
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
# Open shift — Step 1: choose point
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
        "🟢 <b>Начать смену</b>\n\nВыберите точку:",
        reply_markup=shift_open_points_keyboard(today_planned, points_map),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Open shift — Step 2: point selected → send code to PVZ email
# ---------------------------------------------------------------------------

@router.callback_query(OpenShiftState.waiting_point, F.data.startswith("openpoint:"))
async def cb_open_point_selected(callback: CallbackQuery, state: FSMContext) -> None:
    point_id = int(callback.data.split(":")[1])

    async with SessionLocal() as session:
        actor = await ensure_actor(callback, session)
        if not actor:
            await state.clear()
            return

        point = (await session.execute(select(Point).where(Point.id == point_id))).scalar_one_or_none()
        if not point:
            await state.clear()
            await callback.message.edit_text("❌ Точка не найдена.", reply_markup=None)
            await callback.answer()
            return

        if not point.email:
            # No email configured — open shift directly
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
                await callback.message.edit_text("❌ Плановая смена не найдена.", reply_markup=None)
                await callback.answer()
                return

            now = datetime.now(TZ).replace(tzinfo=None)
            shift_repo = ShiftRepo(session)
            shift = await shift_repo.create_open_shift(
                user_id=actor.id,
                point_id=point.id,
                shift_date=now.date(),
                opened_at=now,
                open_lat=0.0,
                open_lon=0.0,
                open_distance_m=0.0,
                open_geo_status=GeoStatus.OK,
                open_approval_status=ApprovalStatus.APPROVED,
            )
            point_name = point.name

        else:
            # Send code to point email
            svc = EmailService(settings)
            today = datetime.now(TZ).date()
            try:
                await svc.send_shift_open_code(
                    db=session,
                    user_id=actor.id,
                    point_id=point_id,
                    shift_date=today,
                    point_email=point.email,
                    point_name=point.name,
                    employee_name=actor.full_name,
                )
            except Exception:
                await state.clear()
                await callback.message.edit_text(
                    "❌ Не удалось отправить код. Попробуйте позже или обратитесь к администратору.",
                    reply_markup=None,
                )
                await callback.message.answer("📋 Меню", reply_markup=MAIN_MENU)
                await callback.answer()
                return

            await state.update_data(point_id=point_id, point_name=point.name)
            await state.set_state(OpenShiftState.waiting_code)
            await callback.message.edit_text(
                f"📧 <b>Код отправлен!</b>\n\n"
                f"На почту точки <b>{point.name}</b> отправлен 4-значный код.\n"
                "Введите его в ответном сообщении:",
                reply_markup=None,
            )
            await callback.answer()
            return

    # No-email path: shift already created above
    await state.clear()
    await callback.message.edit_text(
        f"🟢 <b>Смена начата!</b>\n\n"
        f"📍 {point_name}\n"
        f"⏰ {now:%H:%M}",
        reply_markup=None,
    )
    await callback.message.answer("📋 Меню", reply_markup=MAIN_MENU)
    await callback.answer()

    await notify.notify_shift_opened(
        employee_name=actor.full_name,
        point_name=point_name,
        opened_at_str=f"{now:%H:%M}",
        geo_ok=True,
    )


# ---------------------------------------------------------------------------
# Open shift — Step 3: user enters code
# ---------------------------------------------------------------------------

@router.message(OpenShiftState.waiting_code, F.text)
async def fsm_open_code(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    point_id = data.get("point_id")
    point_name = data.get("point_name", "")
    code_input = (message.text or "").strip()

    if not point_id:
        await state.clear()
        await message.answer("⚠️ Ошибка. Начните заново.", reply_markup=MAIN_MENU)
        return

    async with SessionLocal() as session:
        actor = await ensure_actor(message, session)
        if not actor:
            await state.clear()
            return

        today = datetime.now(TZ).date()
        svc = EmailService(settings)
        ok = await svc.verify_shift_open_code(
            db=session,
            user_id=actor.id,
            point_id=point_id,
            shift_date=today,
            code=code_input,
        )

        if not ok:
            await message.answer(
                "❌ Неверный или просроченный код. Попробуйте ещё раз или нажмите /cancel."
            )
            return

        # Verify planned shift still exists
        planned = (await session.execute(
            select(PlannedShift).where(
                PlannedShift.user_id == actor.id,
                PlannedShift.shift_date == today,
                PlannedShift.point_id == point_id,
            )
        )).scalar_one_or_none()
        if not planned:
            await state.clear()
            await message.answer("❌ Плановая смена не найдена.")
            await message.answer("📋 Меню", reply_markup=MAIN_MENU)
            return

        now = datetime.now(TZ).replace(tzinfo=None)
        shift_repo = ShiftRepo(session)
        await shift_repo.create_open_shift(
            user_id=actor.id,
            point_id=point_id,
            shift_date=now.date(),
            opened_at=now,
            open_lat=0.0,
            open_lon=0.0,
            open_distance_m=0.0,
            open_geo_status=GeoStatus.OK,
            open_approval_status=ApprovalStatus.APPROVED,
        )

    await state.clear()
    await message.answer(
        f"🟢 <b>Смена начата!</b>\n\n"
        f"📍 {point_name}\n"
        f"⏰ {now:%H:%M}\n"
        f"✅ Код подтверждён",
        reply_markup=MAIN_MENU,
    )

    await notify.notify_shift_opened(
        employee_name=actor.full_name,
        point_name=point_name,
        opened_at_str=f"{now:%H:%M}",
        geo_ok=True,
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

        from app.db.repositories import GeofenceExceptionRepo
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
