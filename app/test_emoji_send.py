import asyncio

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_settings


CUSTOM_EMOJI_TEST = (
    "<b>PREMIUM CUSTOM EMOJI TEST</b>\n\n"
    '<tg-emoji emoji-id="5199749070830197566">🎁</tg-emoji> Sovg‘a\n'
    '<tg-emoji emoji-id="5436040291507247633">🎉</tg-emoji> Bayram\n'
    '<tg-emoji emoji-id="5472164874886846699">✨</tg-emoji> Yaltirash\n'
    '<tg-emoji emoji-id="5435957248314579621">⭐️</tg-emoji> Yulduz\n'
    '<tg-emoji emoji-id="5409008750893734809">🏆</tg-emoji> Kubok\n\n'
    "<i>Premium Custom Emoji tekshiruvi.</i>"
)


async def main():
    settings = get_settings()

    # Guruh ID .env faylidan olinadi.
    chat_id = settings.target_group_id

    if not chat_id:
        print("XATOLIK: TARGET_GROUP_ID topilmadi!")
        print("app/.env emas, loyiha asosiy .env faylini tekshiring.")
        return

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        )
    )

    try:
        sent = await bot.send_message(
            chat_id=chat_id,
            text=CUSTOM_EMOJI_TEST
        )

        print("MUVAFFAQIYATLI!")
        print(f"Guruh ID: {chat_id}")
        print(f"Xabar ID: {sent.message_id}")

    except Exception as error:
        print(f"XATOLIK: {type(error).__name__}: {error}")

    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())