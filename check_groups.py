import asyncio
from sqlalchemy import select
from app.database import SessionLocal
from app.models import GroupConfig

async def main():
    async with SessionLocal() as session:
        groups = (await session.scalars(select(GroupConfig))).all()
        print("GURUHLAR SONI:", len(groups))

        for group in groups:
            print("ID:", group.chat_id)
            print("NOMI:", group.title)
            print("FAOL:", group.is_active)
            print("-" * 25)

asyncio.run(main())
