import asyncio

from aiogram import Bot

from app.config import get_settings


CUSTOM_EMOJI_IDS = [
    "5199749070830197566",
    "5436040291507247633",
    "5472164874886846699",
    "5435957248314579621",
    "5409008750893734809",
]


async def main():
    settings = get_settings()
    bot = Bot(token=settings.bot_token)

    try:
        stickers = await bot.get_custom_emoji_stickers(
            custom_emoji_ids=CUSTOM_EMOJI_IDS
        )

        print(f"\nTekshirilgan ID: {len(CUSTOM_EMOJI_IDS)}")
        print(f"Topilgan emoji: {len(stickers)}\n")

        for sticker in stickers:
            print(
                f"Emoji: {sticker.emoji} | "
                f"Set: {sticker.set_name} | "
                f"File ID: {sticker.file_id}"
            )

    except Exception as error:
        print(f"XATOLIK: {error}")

    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())