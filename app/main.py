"""Entry point for Gogol-Mogol bot."""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import config
from app.database import engine, async_session
from app.models import Base, User
from app.middlewares.auth import AuthMiddleware
from app.handlers import common, sous_chef, cook, owner
from app.services.reports import daily_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(__name__)


async def send_daily_report(bot: Bot) -> None:
    """Scheduled task: send daily report to owner at ~23:45."""
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.role.in_(["owner", "sous_chef"]))
        )
        recipients = result.scalars().all()
        text = await daily_report(session, date.today())

    for u in recipients:
        try:
            await bot.send_message(u.telegram_id, text)
        except Exception as e:
            log.error("Failed to send daily report to %s: %s", u.telegram_id, e)


async def remind_hours(bot: Bot) -> None:
    """Scheduled task at 22:00: remind if hours not entered for today."""
    async with async_session() as session:
        from app.services.cook_service import get_active_cooks, get_shifts_for_date
        from sqlalchemy import select as sa_select
        cooks = await get_active_cooks(session)
        shifts = await get_shifts_for_date(session, date.today())
        entered_ids = {s.cook_id for s in shifts}
        missing = [c for c in cooks if c.id not in entered_ids]
        if not missing:
            return
        result = await session.execute(
            sa_select(User).where(User.role.in_(["owner", "sous_chef"]))
        )
        managers = result.scalars().all()

    text = "\u23f0 Не внесены часы за сегодня:\n"
    text += "\n".join(f"\u23f3 {c.name}" for c in missing)
    text += "\n\nВнесите через меню."
    for m in managers:
        try:
            await bot.send_message(m.telegram_id, text)
        except Exception:
            pass


async def remind_revenue(bot: Bot) -> None:
    """Scheduled task at 23:00: remind if revenue not entered for today."""
    async with async_session() as session:
        from app.services.cook_service import get_revenue
        from sqlalchemy import select as sa_select
        rev = await get_revenue(session, date.today())
        if rev:
            return
        result = await session.execute(
            sa_select(User).where(User.role.in_(["owner", "sous_chef"]))
        )
        managers = result.scalars().all()

    for m in managers:
        try:
            await bot.send_message(
                m.telegram_id,
                "\u26a0\ufe0f Выручка за сегодня не внесена!\nВнесите через меню \u2192 \U0001f4b0 Выручка",
            )
        except Exception:
            pass


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    bot = Bot(token=config.bot_token)
    common.set_bot(bot)
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.middleware(AuthMiddleware())

    dp.include_router(common.cancel_router)  # first — catches "Отмена"
    dp.include_router(sous_chef.router)
    dp.include_router(cook.router)
    dp.include_router(owner.router)
    dp.include_router(common.router)  # last — contains fallback handler

    scheduler = AsyncIOScheduler(timezone="Asia/Almaty")
    scheduler.add_job(send_daily_report, "cron", hour=23, minute=45, args=[bot])
    scheduler.add_job(remind_hours, "cron", hour=22, minute=0, args=[bot])
    scheduler.add_job(remind_revenue, "cron", hour=23, minute=0, args=[bot])
    scheduler.start()

    log.info("Bot starting...")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
