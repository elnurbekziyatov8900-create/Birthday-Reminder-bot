
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_settings
from app.database import init_db, close_db
from app.handlers import router
from app.scheduler import setup_scheduler


async def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger = logging.getLogger(__name__)

    if not settings.admin_ids:
        raise RuntimeError(
            "ADMIN_USER_IDS bo‘sh. "
            ".env fayliga Telegram ID raqamingizni kiriting."
        )

    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
        ),
    )

    dp = Dispatcher()
    dp.include_router(router)

    scheduler = None

    try:
        scheduler = setup_scheduler(bot)
        scheduler.start()

        logger.info("Tug‘ilgan kun scheduler ishga tushdi.")
        logger.info("Telegram bot pollingni boshlamoqda.")

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    except Exception:
        logger.exception("Bot ishlashida xatolik yuz berdi.")
        raise

    finally:
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler to‘xtatildi.")

        await bot.session.close()
        await close_db()

        logger.info("Bot va ma’lumotlar bazasi resurslari yopildi.")


if __name__ == "__main__":
    asyncio.run(main())

