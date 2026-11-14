import asyncio
import os
from aiogram import Bot

async def main():
    bot = Bot(token=os.environ["BOT_TOKEN"])
    try:
        chat = await bot.get_chat(3997226341)
        print("CHAT TOPILDI:", chat.title)
        print("CHAT ID:", chat.id)

        me = await bot.me()
        member = await bot.get_chat_member(3997226341, me.id)
        print("BOT STATUS:", member.status)

    except Exception as e:
        print("XATO:", type(e).__name__, str(e))
    finally:
        await bot.session.close()

asyncio.run(main())
