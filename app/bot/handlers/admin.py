from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.bot.context import ensure_actor
from app.bot.helpers import parse_date_iso, parse_decimal
from app.bot.keyboards import points_keyboard
from app.bot.states import ExpenseState
from app.config import get_settings
from app.db.models import AdjustmentType, ApprovalStatus, BrandEnum, RoleEnum
from app.db.repositories import (
    AssignmentRepo,
    ConfirmationRepo,
    ExpenseRepo,
    GeofenceExceptionRepo,
    PointRepo,
    ShiftRepo,
    UserRepo,
    ManualAdjustmentRepo,
)
from app.db.session import SessionLocal
from app.services.lesnoy_catalog import LESNOY_CITY_PREFIX, LESNOY_DEFAULT_POINTS
from app.services.payroll import PayrollService
from app.services.reports import ReportService
from app.services.sync import GoogleSyncService
from app.utils.dates import payroll_period_for_payout
from app.utils.text import money

router = Router(name="admin")
settings = get_settings()


async def _ensure_admin_message(message: Message):
    async with SessionLocal() as session:
        actor = await ensure_actor(message, session)
        if not actor:
            return None
        if actor.role != RoleEnum.ADMIN and actor.telegram_id not in settings.admin_ids:
            await message.answer("Доступно только администратору")
            return None
        return actor


async def _ensure_admin_callback(callback: CallbackQuery):
    async with SessionLocal() as session:
        actor = await ensure_actor(callback, session)
        if not actor:
            return None
        if actor.role != RoleEnum.ADMIN and actor.telegram_id not in settings.admin_ids:
            await callback.answer("Только для админа", show_alert=True)
            return None
        return actor


def _format_point_line(point) -> str:
    return (
        f"id={point.id} | {point.brand.value.upper()} | {point.name} | "
        f"{point.address} | {point.work_start:%H:%M}-{point.work_end:%H:%M} | "
        f"active={point.is_active}"
    )


def _format_user_line(user) -> str:
    phone = user.phone or "-"
    return (
        f"id={user.id} | tg={user.telegram_id} | {user.role.value} | "
        f"{user.full_name} | phone={phone} | active={user.is_active}"
    )


@router.message(Command("cancel"))
async def cancel_state(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено")


@router.message(Command("admin_help"))
async def admin_help(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    text = (
        "Админ-команды:\n"
        "/admin_list_users\n"
        "/admin_add_user tg_id;role;ФИО;phone;manager_bonus_type\n"
        "/admin_delete_user tg_id\n"
        "/admin_restore_user tg_id\n"
        "/admin_list_points\n"
        "/admin_add_point name;address;brand;lat;lon;radius;work_start;work_end\n"
        "/admin_delete_point point_id\n"
        "/admin_restore_point point_id\n"
        "/admin_seed_lesnoy_points [lat lon radius]\n"
        "/admin_assign_rate tg_id;point_name;shift_rate;hourly_rate;is_primary (ставки сотрудника)\n"
        "/admin_add_adjustment tg_id;period_start;period_end;type;amount;comment\n"
        "/admin_sync [YYYY-MM-DD YYYY-MM-DD]\n"
        "/admin_payroll <10|25> [YYYY-MM-DD ref_date] [critical_code]\n"
        "/admin_report YYYY-MM-DD YYYY-MM-DD\n"
        "/admin_expenses YYYY-MM-DD YYYY-MM-DD\n"
        "/admin_confirmations [YYYY-MM-DD]\n"
        "/admin_geo_pending"
    )
    await message.answer(text)


@router.message(F.text == "Админ: управление")
async def admin_manage_button(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    await message.answer(
        "Управление сотрудниками и точками:\n"
        "/admin_list_users\n"
        "/admin_add_user tg_id;role;ФИО;phone;manager_bonus_type\n"
        "/admin_delete_user tg_id\n"
        "/admin_restore_user tg_id\n"
        "/admin_list_points\n"
        "/admin_add_point name;address;brand;lat;lon;radius;work_start;work_end\n"
        "/admin_delete_point point_id\n"
        "/admin_restore_point point_id\n"
        "/admin_seed_lesnoy_points [lat lon radius]"
    )


@router.message(F.text == "Админ: синхронизация")
async def admin_sync_button(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    period_start = date(today.year, today.month, 1)

    async with SessionLocal() as session:
        sync_service = GoogleSyncService(session, settings)
        summary = await sync_service.sync_period(period_start, today)

    await message.answer(
        f"Синхронизация завершена: main={summary.main_imported}, disputes={summary.disputes_imported}"
    )


@router.message(Command("admin_sync"))
async def admin_sync(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    args = message.text.split()[1:]
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()

    if len(args) == 0:
        period_start = date(today.year, today.month, 1)
        period_end = today
    elif len(args) == 2:
        try:
            period_start = parse_date_iso(args[0])
            period_end = parse_date_iso(args[1])
        except ValueError as exc:
            await message.answer(str(exc))
            return
    else:
        await message.answer("Формат: /admin_sync [YYYY-MM-DD YYYY-MM-DD]")
        return

    async with SessionLocal() as session:
        sync_service = GoogleSyncService(session, settings)
        summary = await sync_service.sync_period(period_start, period_end)

    await message.answer(
        f"Синхронизация завершена за {period_start}..{period_end}: "
        f"main={summary.main_imported}, disputes={summary.disputes_imported}"
    )


@router.message(F.text == "Админ: расчет ЗП")
async def admin_payroll_button(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return
    await message.answer("Используйте: /admin_payroll <10|25> [YYYY-MM-DD ref_date] [critical_code]")


@router.message(Command("admin_payroll"))
async def admin_payroll(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    args = message.text.split()[1:]
    if len(args) < 1:
        await message.answer("Формат: /admin_payroll <10|25> [YYYY-MM-DD ref_date] [critical_code]")
        return

    try:
        payout_day = int(args[0])
    except ValueError:
        await message.answer("Первый аргумент должен быть 10 или 25")
        return

    if payout_day not in (10, 25):
        await message.answer("Поддерживаются только дни выплаты: 10 или 25")
        return

    tz = ZoneInfo(settings.timezone)
    ref_date = datetime.now(tz).date()
    provided_code = None

    if len(args) >= 2:
        # Если второй аргумент похож на дату, используем как дату
        if "-" in args[1]:
            try:
                ref_date = parse_date_iso(args[1])
            except ValueError as exc:
                await message.answer(str(exc))
                return
            if len(args) >= 3:
                provided_code = args[2]
        else:
            provided_code = args[1]

    if settings.critical_code:
        if provided_code != settings.critical_code:
            await message.answer("Неверный или отсутствующий critical_code")
            return

    period_start, period_end = payroll_period_for_payout(payout_day, ref_date)

    async with SessionLocal() as session:
        sync_service = GoogleSyncService(session, settings)
        await sync_service.sync_period(period_start, period_end)

        payroll_service = PayrollService(session, settings)
        run_id, rows = await payroll_service.run_payroll(
            period_start=period_start,
            period_end=period_end,
            payout_day=payout_day,
            generated_by=actor.id,
        )

        report_service = ReportService()
        summary_file = report_service.export_payroll_summary_xlsx(period_start, period_end, rows)
        sheets_file = report_service.export_employee_payroll_sheets(period_start, period_end, rows)

    total = sum((r.total_amount_rub for r in rows), Decimal("0"))
    await message.answer(
        f"Расчет сформирован: run_id={run_id}\n"
        f"Период: {period_start}..{period_end}\n"
        f"Сотрудников: {len(rows)}\n"
        f"Итого к выплате: {money(total)}"
    )

    await message.answer_document(FSInputFile(summary_file))
    await message.answer_document(FSInputFile(sheets_file))


@router.message(F.text == "Админ: отчеты")
async def admin_reports_button(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    await message.answer(
        "Используйте:\n"
        "/admin_report YYYY-MM-DD YYYY-MM-DD - смены и расходы\n"
        "/admin_expenses YYYY-MM-DD YYYY-MM-DD - только расходы\n"
        "/admin_confirmations [YYYY-MM-DD] - подтверждения"
    )


@router.message(Command("admin_report"))
async def admin_report(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    args = message.text.split()[1:]
    if len(args) != 2:
        await message.answer("Формат: /admin_report YYYY-MM-DD YYYY-MM-DD")
        return

    try:
        period_start = parse_date_iso(args[0])
        period_end = parse_date_iso(args[1])
    except ValueError as exc:
        await message.answer(str(exc))
        return

    async with SessionLocal() as session:
        shift_repo = ShiftRepo(session)
        expense_repo = ExpenseRepo(session)
        user_repo = UserRepo(session)
        point_repo = PointRepo(session)

        shifts = await shift_repo.list_closed_between(period_start, period_end)
        expenses = await expense_repo.list_period(period_start, period_end)

        users = await user_repo.list_all()
        points = await point_repo.list_all()

        user_map = {u.id: u for u in users}
        point_map = {p.id: p for p in points}

        report_service = ReportService()
        shifts_file = report_service.export_shifts_csv(period_start, period_end, shifts, user_map, point_map)
        expenses_file = report_service.export_expenses_csv(period_start, period_end, expenses, point_map)

    await message.answer_document(FSInputFile(shifts_file))
    await message.answer_document(FSInputFile(expenses_file))


@router.message(Command("admin_expenses"))
async def admin_expenses_report(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    args = message.text.split()[1:]
    if len(args) != 2:
        await message.answer("Формат: /admin_expenses YYYY-MM-DD YYYY-MM-DD")
        return

    try:
        period_start = parse_date_iso(args[0])
        period_end = parse_date_iso(args[1])
    except ValueError as exc:
        await message.answer(str(exc))
        return

    async with SessionLocal() as session:
        expense_repo = ExpenseRepo(session)
        point_repo = PointRepo(session)

        expenses = await expense_repo.list_period(period_start, period_end)
        points = await point_repo.list_all()
        point_map = {p.id: p for p in points}

        report_service = ReportService()
        expenses_file = report_service.export_expenses_csv(period_start, period_end, expenses, point_map)

    await message.answer_document(FSInputFile(expenses_file))


@router.message(Command("admin_confirmations"))
async def admin_confirmations(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    args = message.text.split()[1:]
    tz = ZoneInfo(settings.timezone)
    target_date = (datetime.now(tz).date() + timedelta(days=1)) if not args else None
    try:
        if args:
            target_date = parse_date_iso(args[0])
    except ValueError as exc:
        await message.answer(str(exc))
        return

    async with SessionLocal() as session:
        confirmation_repo = ConfirmationRepo(session)
        user_repo = UserRepo(session)

        rows = await confirmation_repo.summary(target_date)
        users = await user_repo.list_all()
        user_map = {u.id: u.full_name for u in users}

    if not rows:
        await message.answer(f"По дате {target_date} подтверждений нет")
        return

    lines = [f"{user_map.get(r.user_id, r.user_id)}: {r.status.value}" for r in rows]
    await message.answer(f"Подтверждения на {target_date}:\n" + "\n".join(lines))


@router.message(Command("admin_list_users"))
async def admin_list_users(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    async with SessionLocal() as session:
        user_repo = UserRepo(session)
        users = await user_repo.list_all()

    if not users:
        await message.answer("Пользователи не найдены")
        return

    lines = [_format_user_line(u) for u in users]
    await message.answer("Пользователи:\n" + "\n".join(lines[:150]))


@router.message(Command("admin_delete_user"))
async def admin_delete_user(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    args = message.text.split()[1:]
    if len(args) != 1:
        await message.answer("Формат: /admin_delete_user tg_id")
        return

    try:
        tg_id = int(args[0])
    except ValueError:
        await message.answer("tg_id должен быть числом")
        return

    async with SessionLocal() as session:
        user_repo = UserRepo(session)
        assignment_repo = AssignmentRepo(session)

        user = await user_repo.get_by_tg_id(tg_id)
        if not user:
            await message.answer("Пользователь не найден")
            return

        if user.telegram_id == actor.telegram_id:
            await message.answer("Нельзя деактивировать самого себя")
            return

        if user.role == RoleEnum.ADMIN and user.telegram_id in settings.admin_ids:
            await message.answer("Этот админ закреплен в ADMIN_IDS, деактивация запрещена")
            return

        await user_repo.set_active(user.id, False)
        await assignment_repo.set_active_by_user(user.id, False)

    await message.answer(f"Пользователь деактивирован: tg_id={tg_id}")


@router.message(Command("admin_restore_user"))
async def admin_restore_user(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    args = message.text.split()[1:]
    if len(args) != 1:
        await message.answer("Формат: /admin_restore_user tg_id")
        return

    try:
        tg_id = int(args[0])
    except ValueError:
        await message.answer("tg_id должен быть числом")
        return

    async with SessionLocal() as session:
        user_repo = UserRepo(session)
        assignment_repo = AssignmentRepo(session)

        user = await user_repo.set_active_by_tg_id(tg_id, True)
        if not user:
            await message.answer("Пользователь не найден")
            return
        await assignment_repo.set_active_by_user(user.id, True)

    await message.answer(f"Пользователь восстановлен: tg_id={tg_id}")


@router.message(Command("admin_list_points"))
async def admin_list_points(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    async with SessionLocal() as session:
        point_repo = PointRepo(session)
        points = await point_repo.list_all()

    if not points:
        await message.answer("Точки не найдены")
        return

    lines = [_format_point_line(p) for p in points]
    await message.answer("Точки:\n" + "\n".join(lines[:150]))


@router.message(Command("admin_delete_point"))
async def admin_delete_point(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    args = message.text.split()[1:]
    if len(args) != 1:
        await message.answer("Формат: /admin_delete_point point_id")
        return

    try:
        point_id = int(args[0])
    except ValueError:
        await message.answer("point_id должен быть числом")
        return

    async with SessionLocal() as session:
        point_repo = PointRepo(session)
        assignment_repo = AssignmentRepo(session)

        point = await point_repo.set_active(point_id, False)
        if not point:
            await message.answer("Точка не найдена")
            return
        await assignment_repo.set_active_by_point(point_id, False)

    await message.answer(f"Точка деактивирована: {point.name} (id={point.id})")


@router.message(Command("admin_restore_point"))
async def admin_restore_point(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    args = message.text.split()[1:]
    if len(args) != 1:
        await message.answer("Формат: /admin_restore_point point_id")
        return

    try:
        point_id = int(args[0])
    except ValueError:
        await message.answer("point_id должен быть числом")
        return

    async with SessionLocal() as session:
        point_repo = PointRepo(session)
        assignment_repo = AssignmentRepo(session)

        point = await point_repo.set_active(point_id, True)
        if not point:
            await message.answer("Точка не найдена")
            return
        await assignment_repo.set_active_by_point(point_id, True)

    await message.answer(f"Точка восстановлена: {point.name} (id={point.id})")


@router.message(Command("admin_seed_lesnoy_points"))
async def admin_seed_lesnoy_points(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    args = message.text.split()[1:]
    lat = 58.6352
    lon = 59.7852
    radius = 150

    if args:
        if len(args) != 3:
            await message.answer("Формат: /admin_seed_lesnoy_points [lat lon radius]")
            return
        try:
            lat = float(args[0])
            lon = float(args[1])
            radius = int(args[2])
        except ValueError:
            await message.answer("lat/lon/radius заданы некорректно")
            return

    created = 0
    updated = 0

    async with SessionLocal() as session:
        point_repo = PointRepo(session)

        for row in LESNOY_DEFAULT_POINTS:
            existing = await point_repo.get_by_name(row["name"])
            await point_repo.create_or_update(
                name=row["name"],
                address=row["full_address"],
                brand=BrandEnum(row["brand"]),
                latitude=lat,
                longitude=lon,
                radius_m=radius,
                work_start=datetime.strptime(row["work_start"], "%H:%M").time(),
                work_end=datetime.strptime(row["work_end"], "%H:%M").time(),
                is_active=True,
            )
            if existing:
                updated += 1
            else:
                created += 1

    await message.answer(
        "Пункты Лесного синхронизированы:\n"
        f"создано={created}, обновлено={updated}\n"
        f"город={LESNOY_CITY_PREFIX}, radius={radius}м"
    )


@router.message(Command("admin_add_user"))
async def admin_add_user(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    payload = message.text.partition(" ")[2].strip()
    parts = [p.strip() for p in payload.split(";")]
    if len(parts) < 3:
        await message.answer("Формат: /admin_add_user tg_id;role;ФИО;phone;manager_bonus_type")
        return

    try:
        tg_id = int(parts[0])
        role = RoleEnum(parts[1].lower())
        full_name = parts[2]
        phone = parts[3] if len(parts) > 3 and parts[3] else None
        manager_bonus_type = int(parts[4]) if len(parts) > 4 and parts[4] else None
    except Exception as exc:
        await message.answer(f"Ошибка парсинга: {exc}")
        return

    async with SessionLocal() as session:
        user_repo = UserRepo(session)
        user = await user_repo.create_or_update(
            telegram_id=tg_id,
            full_name=full_name,
            role=role,
            phone=phone,
            manager_bonus_type=manager_bonus_type,
        )

    await message.answer(f"Сотрудник сохранен: {user.full_name} ({user.role.value})")


@router.message(Command("admin_add_point"))
async def admin_add_point(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    payload = message.text.partition(" ")[2].strip()
    parts = [p.strip() for p in payload.split(";")]
    if len(parts) < 8:
        await message.answer(
            "Формат: /admin_add_point name;address;brand;lat;lon;radius;work_start;work_end"
        )
        return

    try:
        name = parts[0]
        address = parts[1]
        brand = BrandEnum(parts[2].lower())
        lat = float(parts[3])
        lon = float(parts[4])
        radius = int(parts[5])
        work_start = datetime.strptime(parts[6], "%H:%M").time()
        work_end = datetime.strptime(parts[7], "%H:%M").time()
    except Exception as exc:
        await message.answer(f"Ошибка парсинга: {exc}")
        return

    if "," not in address:
        address = f"{LESNOY_CITY_PREFIX}, {address}"
    if not name.upper().startswith(("WB ", "OZON ")):
        name = f"{brand.value.upper()} {name}"

    async with SessionLocal() as session:
        point_repo = PointRepo(session)
        point = await point_repo.create_or_update(
            name=name,
            address=address,
            brand=brand,
            latitude=lat,
            longitude=lon,
            radius_m=radius,
            work_start=work_start,
            work_end=work_end,
            is_active=True,
        )

    await message.answer(
        f"Точка сохранена: {point.name}\n"
        f"Адрес: {point.address}\n"
        f"Режим: {point.work_start:%H:%M}-{point.work_end:%H:%M}"
    )


@router.message(Command("admin_assign_rate"))
async def admin_assign_rate(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    payload = message.text.partition(" ")[2].strip()
    parts = [p.strip() for p in payload.split(";")]
    if len(parts) < 3:
        await message.answer("Формат: /admin_assign_rate tg_id;point_name;shift_rate;hourly_rate;is_primary")
        return

    try:
        tg_id = int(parts[0])
        point_name = parts[1]
        shift_rate = parse_decimal(parts[2])
        hourly_rate = parse_decimal(parts[3]) if len(parts) > 3 and parts[3] else None
        is_primary = bool(int(parts[4])) if len(parts) > 4 and parts[4] else False
    except Exception as exc:
        await message.answer(f"Ошибка парсинга: {exc}")
        return

    async with SessionLocal() as session:
        user_repo = UserRepo(session)
        point_repo = PointRepo(session)
        assignment_repo = AssignmentRepo(session)

        user = await user_repo.get_by_tg_id(tg_id)
        point = await point_repo.get_by_name(point_name)
        if not user:
            await message.answer("Сотрудник не найден")
            return
        if not point:
            await message.answer("Точка не найдена")
            return

        user.shift_rate_rub = shift_rate
        user.hourly_rate_rub = hourly_rate
        await assignment_repo.assign_user_to_point(
            user_id=user.id,
            point_id=point.id,
            shift_rate_rub=shift_rate,
            hourly_rate_rub=hourly_rate,
            is_primary=is_primary,
        )

    await message.answer("Ставка сотрудника сохранена и назначение обновлено")


@router.message(Command("admin_add_adjustment"))
async def admin_add_adjustment(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    payload = message.text.partition(" ")[2].strip()
    parts = [p.strip() for p in payload.split(";")]
    if len(parts) < 5:
        await message.answer(
            "Формат: /admin_add_adjustment tg_id;period_start;period_end;type;amount;comment"
        )
        return

    try:
        tg_id = int(parts[0])
        period_start = parse_date_iso(parts[1])
        period_end = parse_date_iso(parts[2])
        adjustment_type = AdjustmentType(parts[3].lower())
        amount = parse_decimal(parts[4])
        comment = parts[5] if len(parts) > 5 else None
    except Exception as exc:
        await message.answer(f"Ошибка парсинга: {exc}")
        return

    async with SessionLocal() as session:
        user_repo = UserRepo(session)
        adjustment_repo = ManualAdjustmentRepo(session)

        user = await user_repo.get_by_tg_id(tg_id)
        if not user:
            await message.answer("Сотрудник не найден")
            return

        await adjustment_repo.add(
            user_id=user.id,
            period_start=period_start,
            period_end=period_end,
            amount_rub=amount,
            adjustment_type=adjustment_type,
            comment=comment,
            created_by=actor.id,
        )

    await message.answer("Корректировка сохранена")


@router.message(F.text == "Админ: расходы")
async def expense_start(message: Message, state: FSMContext) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    async with SessionLocal() as session:
        point_repo = PointRepo(session)
        points = await point_repo.list_active()

    if not points:
        await message.answer("Активных точек нет")
        return

    await state.set_state(ExpenseState.waiting_point)
    await message.answer("Выберите точку:", reply_markup=points_keyboard(points, "expensepoint"))


@router.callback_query(ExpenseState.waiting_point, F.data.startswith("expensepoint:"))
async def expense_select_point(callback: CallbackQuery, state: FSMContext) -> None:
    actor = await _ensure_admin_callback(callback)
    if not actor:
        return

    point_id = int(callback.data.split(":", maxsplit=1)[1])
    await state.update_data(point_id=point_id)
    await state.set_state(ExpenseState.waiting_category)
    await callback.message.answer("Введите категорию расхода")
    await callback.answer()


@router.message(ExpenseState.waiting_category)
async def expense_category(message: Message, state: FSMContext) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    category = (message.text or "").strip()
    if not category:
        await message.answer("Категория не может быть пустой")
        return

    await state.update_data(category=category)
    await state.set_state(ExpenseState.waiting_amount)
    await message.answer("Введите сумму расхода")


@router.message(ExpenseState.waiting_amount)
async def expense_amount(message: Message, state: FSMContext) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    try:
        amount = parse_decimal(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await state.update_data(amount=str(amount))
    await state.set_state(ExpenseState.waiting_description)
    await message.answer("Введите описание расхода (или '-')")


@router.message(ExpenseState.waiting_description)
async def expense_description(message: Message, state: FSMContext) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    data = await state.get_data()
    point_id = data.get("point_id")
    category = data.get("category")
    amount = Decimal(data.get("amount"))
    description = (message.text or "").strip()
    if description == "-":
        description = None

    tz = ZoneInfo(settings.timezone)
    expense_date = datetime.now(tz).date()

    async with SessionLocal() as session:
        expense_repo = ExpenseRepo(session)
        await expense_repo.add(
            point_id=point_id,
            expense_date=expense_date,
            amount_rub=amount,
            category=category,
            description=description,
            created_by=actor.id,
        )

    await state.clear()
    await message.answer("Расход сохранен")


@router.message(Command("admin_geo_pending"))
async def admin_geo_pending(message: Message) -> None:
    actor = await _ensure_admin_message(message)
    if not actor:
        return

    async with SessionLocal() as session:
        ge_repo = GeofenceExceptionRepo(session)
        shift_repo = ShiftRepo(session)
        user_repo = UserRepo(session)

        rows = await ge_repo.list_pending()
        if not rows:
            await message.answer("Нет гео-исключений в ожидании")
            return

        for row in rows:
            shift = await shift_repo.get_by_id(row.shift_id)
            user = await user_repo.get_by_id(shift.user_id) if shift else None

            from app.bot.keyboards import geofence_approve_keyboard

            await message.answer(
                (
                    f"exception_id={row.id}\n"
                    f"event={row.event}\n"
                    f"distance={float(row.distance_m):.1f}m\n"
                    f"employee={(user.full_name if user else shift.user_id if shift else '-') }\n"
                    f"shift_id={row.shift_id}"
                ),
                reply_markup=geofence_approve_keyboard(row.id, row.shift_id, row.event),
            )


@router.callback_query(F.data.startswith("geoapprove:"))
async def geoapprove(callback: CallbackQuery) -> None:
    actor = await _ensure_admin_callback(callback)
    if not actor:
        return

    parts = callback.data.split(":")
    if len(parts) != 6:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    _, exception_id_raw, shift_id_raw, event, decision = parts

    try:
        exception_id = int(exception_id_raw)
        shift_id = int(shift_id_raw)
    except ValueError:
        await callback.answer("Некорректный id", show_alert=True)
        return

    status = ApprovalStatus.APPROVED if decision == "ok" else ApprovalStatus.REJECTED

    async with SessionLocal() as session:
        ge_repo = GeofenceExceptionRepo(session)
        shift_repo = ShiftRepo(session)
        user_repo = UserRepo(session)

        await ge_repo.set_status(exception_id, status, reviewed_by=actor.id)
        if event == "open":
            await shift_repo.update_open_approval(shift_id, status)
        elif event == "close":
            await shift_repo.update_close_approval(shift_id, status)

        shift = await shift_repo.get_by_id(shift_id)
        if shift:
            user = await user_repo.get_by_id(shift.user_id)
            if user:
                try:
                    await callback.bot.send_message(
                        user.telegram_id,
                        f"Администратор {('подтвердил' if status == ApprovalStatus.APPROVED else 'отклонил')} гео-исключение по смене #{shift_id}",
                    )
                except Exception:
                    pass

    await callback.message.answer(
        f"Решение сохранено: exception_id={exception_id} -> {status.value}"
    )
    await callback.answer()
