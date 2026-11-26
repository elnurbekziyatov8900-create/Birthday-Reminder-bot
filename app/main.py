import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeChat, LinkPreviewOptions

from app.config import get_settings
from app.database import close_db, init_db
from app.handlers import router
from app.middlewares import SlowRequestMiddleware, UpdateTimingMiddleware
from app.scheduler import setup_scheduler


ADMIN_COMMANDS = [
    BotCommand(command="birthdays", description="🎂 Barcha tug'ilgan kunlar"),
    BotCommand(command="today", description="🎉 Bugungi tabriklar"),
    BotCommand(command="next", description="⏳ Eng yaqin tug'ilgan kun"),
    BotCommand(command="upcoming", description="🔔 Keyingi 30 kun"),
    BotCommand(command="add", description="➕ Yangi inson qo'shish"),
    BotCommand(command="groups", description="👨‍👩‍👧‍👦 Ulangan guruhlar"),
    BotCommand(command="status", description="📊 Tizim holati"),
    BotCommand(command="help", description="📝 To'liq qo'llanma"),
    BotCommand(command="cancel", description="↩️ Amalni bekor qilish"),
]


async def setup_bot_commands(bot: Bot, admin_ids: set[int]) -> None:
    """Administratorlarning shaxsiy chatida komandalar menyusini o'rnatadi."""

    logger = logging.getLogger(__name__)

    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(
                ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except TelegramAPIError as error:
            # Admin hali botga /start bosmagan bo'lsa, chat topilmaydi.
            logger.warning(
                "Komandalar menyusini o'rnatib bo'lmadi: admin_id=%s, %s",
                admin_id,
                error,
            )


async def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    # aiogram'ning "Update ... is handled" yozuvi o'rniga app.timing ishlatiladi.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)

    if not settings.admin_ids:
        raise RuntimeError(
            "ADMIN_USER_IDS bo'sh. .env fayliga Telegram ID raqamingizni kiriting."
        )

    bot = None
    scheduler = None

    try:
        await init_db()

        bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
                link_preview=LinkPreviewOptions(is_disabled=True),
            ),
        )

        # Tezlikni kuzatish: har bir update vaqti va sekin API so'rovlari.
        bot.session.middleware(SlowRequestMiddleware())

        dp = Dispatcher()
        dp.update.outer_middleware(UpdateTimingMiddleware())
        dp.include_router(router)

        await setup_bot_commands(bot, settings.admin_ids)

        scheduler = setup_scheduler(bot)
        scheduler.start()

        logger.info("Birthday scheduler started.")
        logger.info("Telegram bot polling started.")

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            close_bot_session=False,
        )

    except Exception:
        logger.exception("Bot ishlashida xatolik yuz berdi.")
        raise

    finally:
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")

        try:
            if bot:
                await bot.session.close()
                logger.info("Telegram bot session closed.")
        finally:
            await close_db()


if __name__ == "__main__":
    asyncio.run(main())
