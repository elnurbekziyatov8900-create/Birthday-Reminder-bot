"""app/ui.py dagi barcha animatsiyali emoji ID'larini Telegram orqali tekshiradi.

Ishga tushirish:  python -m app.check_emoji
"""

import asyncio

from aiogram import Bot

from app.config import get_settings
from app.ui import EMOJI


async def main() -> None:
    settings = get_settings()
    bot = Bot(token=settings.bot_token)

    ids = [emoji_id for emoji_id, _ in EMOJI.values()]

    try:
        found: dict[str, object] = {}

        # getCustomEmojiStickers bir so'rovda ko'pi bilan 200 ta ID qabul qiladi.
        for start in range(0, len(ids), 200):
            stickers = await bot.get_custom_emoji_stickers(
                custom_emoji_ids=ids[start:start + 200]
            )
            found.update({sticker.custom_emoji_id: sticker for sticker in stickers})

        print(f"Tekshirilgan: {len(ids)} | Topilgan: {len(found)}\n")

        for key, (emoji_id, fallback) in EMOJI.items():
            sticker = found.get(emoji_id)

            if sticker is None:
                print(f"XATO  {key:16} {fallback}  {emoji_id}  (topilmadi)")
                continue

            kind = "animated" if sticker.is_animated else "video" if sticker.is_video else "static"
            print(f"OK    {key:16} {fallback}  {emoji_id}  {sticker.set_name} / {kind}")

    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
