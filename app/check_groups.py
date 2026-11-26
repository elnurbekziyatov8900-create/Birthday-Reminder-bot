"""Bazadagi guruhlarni va botning ulardagi holatini tekshiradi.

Ishga tushirish:  python -m app.check_groups
"""

import asyncio

from aiogram import Bot
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal, close_db
from app.models import GroupConfig


async def main() -> None:
    settings = get_settings()
    bot = Bot(token=settings.bot_token)

    try:
        async with SessionLocal() as session:
            groups = (await session.scalars(select(GroupConfig))).all()

        print(f"TARGET_GROUP_ID (.env): {settings.target_group_id}")
        print(f"Bazadagi guruhlar soni: {len(groups)}\n")

        me = await bot.me()

        for group in groups:
            print(f"ID: {group.chat_id} | {group.title} | faol: {group.is_active}")

            try:
                chat = await bot.get_chat(group.chat_id)
                member = await bot.get_chat_member(group.chat_id, me.id)
                print(f"  Telegram: {chat.type} '{chat.title}', bot: {member.status}")
            except Exception as error:  # noqa: BLE001
                print(f"  XATO: {type(error).__name__}: {error}")

    finally:
        await bot.session.close()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
