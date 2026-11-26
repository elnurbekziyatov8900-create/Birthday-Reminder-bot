"""Animatsiyali emojilar va tabrik dizaynini sinab ko'rish.

Ishga tushirish:
    python -m app.test_emoji_send            # .env dagi ADMIN_USER_IDS ning birinchisiga
    python -m app.test_emoji_send -100123... # ko'rsatilgan chatga

Eslatma: animatsiyali emojilar faqat bot egasida Telegram Premium bo'lsa
ko'rinadi, aks holda oddiy emoji ko'rsatiladi.
"""

import asyncio
import sys
from datetime import date

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_settings
from app.messaging import split_html_text
from app.services import PersonData, local_today, make_greeting
from app.ui import EMOJI, e


async def main() -> None:
    settings = get_settings()

    if len(sys.argv) > 1:
        chat_id = int(sys.argv[1])
    elif settings.admin_ids:
        chat_id = min(settings.admin_ids)
    else:
        print("XATOLIK: chat ID ko'rsatilmagan va ADMIN_USER_IDS bo'sh.")
        return

    gallery = " ".join(e(key) for key in EMOJI)
    today = local_today()
    sample = PersonData(
        id=0,
        full_name="Namuna Inson",
        birth_date=date(today.year - 25, today.month, min(today.day, 28)),
        photo_file_id=None,
        music_file_id=None,
    )

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    try:
        await bot.send_message(chat_id, f"<b>Animatsiyali emojilar</b>\n\n{gallery}")

        for chunk in split_html_text(make_greeting(sample, today)):
            await bot.send_message(chat_id, chunk)

        print(f"MUVAFFAQIYATLI! Chat ID: {chat_id}")

    except Exception as error:  # noqa: BLE001
        print(f"XATOLIK: {type(error).__name__}: {error}")

    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
