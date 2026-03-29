from __future__ import annotations

import asyncio
import logging
import signal

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import admin_router, employee_router
from app.config import get_settings
from app.db.session import SessionLocal, init_db
from app.services.scheduler import BotScheduler


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    log = logging.getLogger("pvz")

    settings = get_settings()
    await init_db()

    # ── Bot setup ──────────────────────────────────────────────
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(employee_router)
    dp.include_router(admin_router)

    scheduler = BotScheduler(bot=bot, session_factory=SessionLocal, settings=settings)
    scheduler.start()

    # ── Web setup ──────────────────────────────────────────────
    import uvicorn
    from app.web.app import create_app

    web_app = create_app()
    uvi_config = uvicorn.Config(
        web_app,
        host=settings.web_host,
        port=settings.web_port,
        log_level="info",
        loop="none",          # reuse the running event loop
    )
    uvi_server = uvicorn.Server(uvi_config)

    # Prevent uvicorn from installing its own signal handlers
    # (we handle shutdown ourselves).
    uvi_server.install_signal_handlers = lambda: None

    # ── Run both concurrently ──────────────────────────────────
    shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    async def run_bot() -> None:
        log.info("Bot polling started")
        try:
            await dp.start_polling(bot)
        except asyncio.CancelledError:
            pass
        finally:
            log.info("Bot polling stopped")

    async def run_web() -> None:
        log.info("Web server starting on %s:%s", settings.web_host, settings.web_port)
        try:
            await uvi_server.serve()
        except asyncio.CancelledError:
            pass
        finally:
            log.info("Web server stopped")

    async def run_watchdog() -> None:
        await shutdown_event.wait()
        log.info("Shutdown signal received, stopping services …")
        # Stop bot polling gracefully
        await dp.stop_polling()
        # Stop uvicorn
        uvi_server.should_exit = True

    tasks = [
        asyncio.create_task(run_bot(), name="bot"),
        asyncio.create_task(run_web(), name="web"),
        asyncio.create_task(run_watchdog(), name="watchdog"),
    ]

    try:
        await asyncio.gather(*tasks)
    finally:
        scheduler.shutdown()
        await bot.session.close()
        log.info("All services stopped")


if __name__ == "__main__":
    asyncio.run(run())
