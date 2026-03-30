from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.keyboards import tomorrow_confirm_keyboard
from app.config import Settings
from app.db.repositories import ConfirmationRepo, ShiftRepo, UserRepo


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

    def start(self) -> None:
        hour, minute = [int(x) for x in self.settings.confirm_request_time.split(":")]

        self.scheduler.add_job(
            self.send_tomorrow_confirm_requests,
            CronTrigger(hour=hour, minute=minute),
            id="daily_confirm_requests",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.notify_admin_about_unconfirmed,
            CronTrigger(hour=21, minute=0),
            id="daily_unconfirmed_alert",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.notify_admin_about_open_shifts,
            CronTrigger(minute="*/30"),
            id="open_shift_alert",
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

    async def _admin_telegram_ids(self, user_repo: UserRepo) -> list[int]:
        admins = await user_repo.list_admins()
        ids = {a.telegram_id for a in admins}
        ids.update(self.settings.admin_ids)
        return sorted(ids)
