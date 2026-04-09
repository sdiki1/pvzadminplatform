from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards import tomorrow_confirm_keyboard
from app.config import Settings
from app.db.repositories import ConfirmationRepo, PlannedShiftRepo, ShiftRepo, UserRepo


class BotScheduler:
    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker,
        settings: Settings,
    ):
        self.bot = bot
        self.session_factory = session_factory
        self.settings = settings
        self.scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.timezone))
        # Track already-notified (user_id, shift_date) pairs to avoid duplicate alerts
        self._notified_uncovered: set[tuple[int, str]] = set()

    def start(self) -> None:
        req_hour, req_minute = [int(x) for x in self.settings.confirm_request_time.split(":")]
        dl_hour, dl_minute = [int(x) for x in self.settings.confirm_deadline_time.split(":")]

        self.scheduler.add_job(
            self.send_tomorrow_confirm_requests,
            CronTrigger(hour=req_hour, minute=req_minute),
            id="daily_confirm_requests",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.notify_admin_about_unconfirmed,
            CronTrigger(hour=dl_hour, minute=dl_minute),
            id="daily_unconfirmed_alert",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.notify_admin_about_open_shifts,
            CronTrigger(minute="*/30"),
            id="open_shift_alert",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.notify_uncovered_shifts,
            CronTrigger(minute="*/10"),
            id="uncovered_shift_alert",
            replace_existing=True,
        )
        # Reset deduplication cache at midnight every day
        self.scheduler.add_job(
            self._reset_notified_uncovered,
            CronTrigger(hour=0, minute=1),
            id="reset_notified_uncovered",
            replace_existing=True,
        )
        self.scheduler.start()

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)

    async def send_tomorrow_confirm_requests(self) -> None:
        tz = ZoneInfo(self.settings.timezone)
        target_date = (datetime.now(tz) + timedelta(days=1)).date()

        async with self.session_factory() as session:
            user_repo = UserRepo(session)
            employees = await user_repo.list_active_employees()

            for user in employees:
                try:
                    await self.bot.send_message(
                        user.telegram_id,
                        f"Подтвердите выход на {target_date:%d.%m.%Y}",
                        reply_markup=tomorrow_confirm_keyboard(target_date.isoformat()),
                    )
                except Exception:
                    continue

    async def notify_admin_about_unconfirmed(self) -> None:
        tz = ZoneInfo(self.settings.timezone)
        target_date = (datetime.now(tz) + timedelta(days=1)).date()

        async with self.session_factory() as session:
            user_repo = UserRepo(session)
            confirmation_repo = ConfirmationRepo(session)

            employees = await user_repo.list_active_employees()
            employee_ids = [u.id for u in employees]
            unconfirmed_ids = await confirmation_repo.get_unconfirmed_employee_ids(target_date, employee_ids)
            if not unconfirmed_ids:
                return

            id_to_name = {u.id: u.full_name for u in employees}
            lines = [f"- {id_to_name.get(uid, uid)}" for uid in unconfirmed_ids]
            msg = f"Не подтвердили выход на {target_date:%d.%m.%Y}:\n" + "\n".join(lines)

            admin_ids = await self._admin_telegram_ids(user_repo)
            for admin_tg in admin_ids:
                try:
                    await self.bot.send_message(admin_tg, msg)
                except Exception:
                    continue

    async def notify_admin_about_open_shifts(self) -> None:
        tz = ZoneInfo(self.settings.timezone)
        now = datetime.now(tz)
        overdue_threshold = (now - timedelta(hours=14)).replace(tzinfo=None)

        async with self.session_factory() as session:
            shift_repo = ShiftRepo(session)
            user_repo = UserRepo(session)

            overdue = await shift_repo.list_overdue_open(overdue_threshold)
            if not overdue:
                return

            users = await user_repo.list_all()
            user_map = {u.id: u.full_name for u in users}
            lines = []
            for shift in overdue[:20]:
                name = user_map.get(shift.user_id, str(shift.user_id))
                lines.append(f"- {name}: открыта {shift.opened_at:%d.%m %H:%M}, shift_id={shift.id}")

            text = "Есть смены без закрытия более 14 часов:\n" + "\n".join(lines)
            admin_ids = await self._admin_telegram_ids(user_repo)
            for admin_tg in admin_ids:
                try:
                    await self.bot.send_message(admin_tg, text)
                except Exception:
                    continue

    async def notify_uncovered_shifts(self) -> None:
        """Alert admins if a planned shift hasn't been opened 10+ minutes after start time."""
        tz = ZoneInfo(self.settings.timezone)
        now = datetime.now(tz)
        today = now.date()
        threshold_time = (now - timedelta(minutes=10)).time()

        async with self.session_factory() as session:
            planned_repo = PlannedShiftRepo(session)
            user_repo = UserRepo(session)

            uncovered = await planned_repo.list_uncovered_for_today(today, threshold_time)
            if not uncovered:
                return

            # Filter out already-notified entries
            new_uncovered = [
                ps for ps in uncovered
                if (ps.user_id, today.isoformat()) not in self._notified_uncovered
            ]
            if not new_uncovered:
                return

            users = await user_repo.list_all()
            user_map = {u.id: u.full_name for u in users}

            lines = []
            for ps in new_uncovered:
                name = user_map.get(ps.user_id, str(ps.user_id))
                point_name = ps.point.name if ps.point else f"Точка #{ps.point_id}"
                start = ps.start_time or (ps.point.work_start if ps.point else None)
                start_str = start.strftime("%H:%M") if start else "?"
                lines.append(f"- {name} | {point_name} | план {start_str}")
                self._notified_uncovered.add((ps.user_id, today.isoformat()))

            text = f"⚠️ <b>Смены не открыты</b> (прошло 10+ мин):\n\n" + "\n".join(lines)
            admin_ids = await self._admin_telegram_ids(user_repo)
            for admin_tg in admin_ids:
                try:
                    await self.bot.send_message(admin_tg, text, parse_mode="HTML")
                except Exception:
                    continue

    async def _reset_notified_uncovered(self) -> None:
        self._notified_uncovered.clear()

    async def _admin_telegram_ids(self, user_repo: UserRepo) -> list[int]:
        admins = await user_repo.list_admins()
        ids = {a.telegram_id for a in admins}
        ids.update(self.settings.admin_ids)
        return sorted(ids)
