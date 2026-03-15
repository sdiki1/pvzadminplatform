from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.context import ensure_actor
from app.bot.helpers import admin_telegram_ids
from app.bot.keyboards import (
    menu_for_role,
    points_keyboard,
    request_location_keyboard,
    tomorrow_confirm_keyboard,
)
from app.bot.states import CloseShiftState, OpenShiftState
from app.config import get_settings
from app.db.models import ApprovalStatus, ConfirmationStatus, GeoStatus, RoleEnum
from app.db.repositories import (
    AssignmentRepo,
    ConfirmationRepo,
    GeofenceExceptionRepo,
    PointRepo,
    ShiftRepo,
    UserRepo,
)
from app.db.session import SessionLocal
from app.services.geofence import GeofenceService
from app.services.payroll import PayrollService
from app.utils.text import dt, money

router = Router(name="employee")
settings = get_settings()


async def _notify_admins(message: Message, text: str, reply_markup=None) -> None:
    async with SessionLocal() as session:
        ids = await admin_telegram_ids(session, settings)

    for tg_id in ids:
        try:
            await message.bot.send_message(tg_id, text, reply_markup=reply_markup)
        except Exception:
            continue


@router.message(CommandStart())
async def start(message: Message) -> None:
    async with SessionLocal() as session:
        user_repo = UserRepo(session)
        user = await user_repo.get_by_tg_id(message.from_user.id)

        if not user and message.from_user.id in settings.admin_ids:
            full_name = " ".join(filter(None, [message.from_user.last_name, message.from_user.first_name]))
            user = await user_repo.create_or_update(
                telegram_id=message.from_user.id,
                full_name=full_name or str(message.from_user.id),
                role=RoleEnum.ADMIN,
            )

        if not user:
            await message.answer(
                "Вы не зарегистрированы в системе. "
                f"Передайте администратору ваш Telegram ID: `{message.from_user.id}`",
                parse_mode="Markdown",
            )
            return

        await message.answer("Главное меню", reply_markup=menu_for_role(user.role))


@router.message(F.text == "Подтвердить выход на завтра")
async def ask_tomorrow_confirmation(message: Message) -> None:
    tz = ZoneInfo(settings.timezone)
    target_date = (datetime.now(tz) + timedelta(days=1)).date()
    await message.answer(
        f"Подтвердите выход на {target_date:%d.%m.%Y}",
        reply_markup=tomorrow_confirm_keyboard(target_date.isoformat()),
    )


@router.callback_query(F.data.startswith("confirm:"))
async def confirm_tomorrow(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    _, target_date_iso, status_raw = parts
    status = {
        "yes": ConfirmationStatus.YES,
        "no": ConfirmationStatus.NO,
        "unknown": ConfirmationStatus.UNKNOWN,
    }.get(status_raw)
    if not status:
        await callback.answer("Некорректный статус", show_alert=True)
        return

    async with SessionLocal() as session:
        actor = await ensure_actor(callback, session)
        if not actor:
            return

        confirmation_repo = ConfirmationRepo(session)
        target_date = date.fromisoformat(target_date_iso)
        await confirmation_repo.upsert(actor.id, target_date, status)

    await callback.message.answer(f"Сохранено: {target_date:%d.%m.%Y} -> {status.value}")
    await callback.answer()


@router.message(F.text == "Открыть смену")
async def open_shift_start(message: Message, state: FSMContext) -> None:
    async with SessionLocal() as session:
        actor = await ensure_actor(message, session)
        if not actor:
            return

        shift_repo = ShiftRepo(session)
        if await shift_repo.get_open_shift(actor.id):
            await message.answer("У вас уже есть открытая смена.")
            return

        assignment_repo = AssignmentRepo(session)
        point_repo = PointRepo(session)

        assignments = await assignment_repo.list_user_assignments(actor.id)
        points = []
        for assignment in assignments:
            p = await point_repo.get_by_id(assignment.point_id)
            if p and p.is_active:
                points.append(p)

        if not points:
            await message.answer("Нет доступных точек. Обратитесь к администратору.")
            return

    await state.set_state(OpenShiftState.waiting_point)
    await message.answer("Выберите ПВЗ:", reply_markup=points_keyboard(points, "openpoint"))


@router.callback_query(OpenShiftState.waiting_point, F.data.startswith("openpoint:"))
async def open_shift_point(callback: CallbackQuery, state: FSMContext) -> None:
    point_id = int(callback.data.split(":", maxsplit=1)[1])
    await state.update_data(point_id=point_id)
    await state.set_state(OpenShiftState.waiting_location)
    await callback.message.answer("Отправьте геолокацию для открытия смены", reply_markup=request_location_keyboard())
    await callback.answer()


@router.message(OpenShiftState.waiting_location, F.location)
async def open_shift_location(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    point_id = data.get("point_id")
    if not point_id:
        await state.clear()
        await message.answer("Точка не выбрана. Повторите действие.")
        return

    async with SessionLocal() as session:
        actor = await ensure_actor(message, session)
        if not actor:
            await state.clear()
            return

        point_repo = PointRepo(session)
        point = await point_repo.get_by_id(point_id)
        if not point:
            await state.clear()
            await message.answer("Точка не найдена")
            return

        geo_result = GeofenceService.check(point, message.location.latitude, message.location.longitude)
        open_approval = ApprovalStatus.APPROVED if geo_result.status == GeoStatus.OK else ApprovalStatus.PENDING

        shift_repo = ShiftRepo(session)
        tz = ZoneInfo(settings.timezone)
        opened_at = datetime.now(tz).replace(tzinfo=None)

        shift = await shift_repo.create_open_shift(
            user_id=actor.id,
            point_id=point.id,
            shift_date=opened_at.date(),
            opened_at=opened_at,
            open_lat=message.location.latitude,
            open_lon=message.location.longitude,
            open_distance_m=geo_result.distance_m,
            open_geo_status=geo_result.status,
            open_approval_status=open_approval,
        )

        if geo_result.status == GeoStatus.OUTSIDE:
            ge_repo = GeofenceExceptionRepo(session)
            ge = await ge_repo.create(shift.id, "open", geo_result.distance_m)
            from app.bot.keyboards import geofence_approve_keyboard

            await _notify_admins(
                message,
                (
                    f"Отклонение гео при открытии смены\n"
                    f"Сотрудник: {actor.full_name}\n"
                    f"ПВЗ: {point.name}\n"
                    f"Distance: {geo_result.distance_m:.1f} м"
                ),
                reply_markup=geofence_approve_keyboard(ge.id, shift.id, "open"),
            )

    await state.clear()
    await message.answer(
        (
            f"Смена открыта #{shift.id}\n"
            f"ПВЗ: {point.name}\n"
            f"Время: {shift.opened_at:%d.%m.%Y %H:%M}\n"
            f"Гео: {'OK' if geo_result.status == GeoStatus.OK else 'требует подтверждения админа'}"
        )
    )


@router.message(F.text == "Закрыть смену")
async def close_shift_start(message: Message, state: FSMContext) -> None:
    async with SessionLocal() as session:
        actor = await ensure_actor(message, session)
        if not actor:
            return

        shift_repo = ShiftRepo(session)
        shift = await shift_repo.get_open_shift(actor.id)
        if not shift:
            await message.answer("У вас нет открытой смены")
            return

    await state.set_state(CloseShiftState.waiting_location)
    await state.update_data(shift_id=shift.id)
    await message.answer("Отправьте геолокацию для закрытия смены", reply_markup=request_location_keyboard())


@router.message(CloseShiftState.waiting_location, F.location)
async def close_shift_location(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    shift_id = data.get("shift_id")
    if not shift_id:
        await state.clear()
        await message.answer("Смена не найдена. Повторите действие.")
        return

    async with SessionLocal() as session:
        actor = await ensure_actor(message, session)
        if not actor:
            await state.clear()
            return

        shift_repo = ShiftRepo(session)
        point_repo = PointRepo(session)
        ge_repo = GeofenceExceptionRepo(session)

        shift = await shift_repo.get_by_id(shift_id)
        if not shift or shift.user_id != actor.id:
            await state.clear()
            await message.answer("Смена не найдена.")
            return

        point = await point_repo.get_by_id(shift.point_id)
        if not point:
            await state.clear()
            await message.answer("Точка не найдена.")
            return

        geo_result = GeofenceService.check(point, message.location.latitude, message.location.longitude)
        close_approval = ApprovalStatus.APPROVED if geo_result.status == GeoStatus.OK else ApprovalStatus.PENDING

        tz = ZoneInfo(settings.timezone)
        closed_at = datetime.now(tz).replace(tzinfo=None)

        shift = await shift_repo.close_shift(
            shift=shift,
            closed_at=closed_at,
            close_lat=message.location.latitude,
            close_lon=message.location.longitude,
            close_distance_m=geo_result.distance_m,
            close_geo_status=geo_result.status,
            close_approval_status=close_approval,
        )

        if geo_result.status == GeoStatus.OUTSIDE:
            ge = await ge_repo.create(shift.id, "close", geo_result.distance_m)
            from app.bot.keyboards import geofence_approve_keyboard

            await _notify_admins(
                message,
                (
                    f"Отклонение гео при закрытии смены\n"
                    f"Сотрудник: {actor.full_name}\n"
                    f"ПВЗ: {point.name}\n"
                    f"Distance: {geo_result.distance_m:.1f} м"
                ),
                reply_markup=geofence_approve_keyboard(ge.id, shift.id, "close"),
            )

    await state.clear()
    await message.answer(
        (
            f"Смена закрыта #{shift.id}\n"
            f"Длительность: {shift.duration_minutes or 0} мин\n"
            f"Гео: {'OK' if geo_result.status == GeoStatus.OK else 'требует подтверждения админа'}"
        )
    )


@router.message(F.text == "Мои смены")
async def my_shifts(message: Message) -> None:
    async with SessionLocal() as session:
        actor = await ensure_actor(message, session)
        if not actor:
            return

        shift_repo = ShiftRepo(session)
        point_repo = PointRepo(session)

        shifts = await shift_repo.list_user_shifts(actor.id)
        if not shifts:
            await message.answer("Смен пока нет.")
            return

        lines = []
        for s in shifts:
            point = await point_repo.get_by_id(s.point_id)
            point_name = point.name if point else f"id={s.point_id}"
            lines.append(
                f"#{s.id} | {s.shift_date:%d.%m} | {point_name} | {s.state.value} | "
                f"{dt(s.opened_at)} - {dt(s.closed_at)} | {s.duration_minutes or 0} мин"
            )

        await message.answer("Последние смены:\n" + "\n".join(lines))


@router.message(F.text == "Моя ЗП")
async def my_payroll(message: Message) -> None:
    async with SessionLocal() as session:
        actor = await ensure_actor(message, session)
        if not actor:
            return

        payroll_service = PayrollService(session, settings)
        item = await payroll_service.latest_for_user(actor.id)
        if not item:
            await message.answer("Расчеты ЗП пока не сформированы.")
            return

        await message.answer(
            "Последний расчет:\n"
            f"Смены: {item.shifts_count}\n"
            f"Часы: {item.hours_total}\n"
            f"База: {money(item.base_amount_rub)}\n"
            f"Мотивация: {money(item.motivation_amount_rub)}\n"
            f"Бонус выдача: {money(item.issued_bonus_rub)}\n"
            f"Удержания (не оспорено): {money(item.dispute_deduction_rub)}\n"
            f"Бонус менеджера: {money(item.manager_bonus_rub)}\n"
            f"Корректировки: {money(item.adjustments_rub)}\n"
            f"Итого: {money(item.total_amount_rub)}"
        )
