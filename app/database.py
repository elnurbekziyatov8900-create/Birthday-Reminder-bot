from __future__ import annotations

import logging

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


logger = logging.getLogger(__name__)

settings = get_settings()


def prepare_database_url(database_url: str) -> str:
    url = make_url(database_url)

    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+asyncpg")

    if url.drivername != "postgresql+asyncpg":
        raise ValueError(
            "DATABASE_URL async PostgreSQL driveridan foydalanishi kerak."
        )

    return url.render_as_string(hide_password=False)


DATABASE_URL = prepare_database_url(settings.database_url)


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
)


SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


# Eski bazalarni joriy modelga moslashtiruvchi idempotent SQL buyruqlar.
# `create_all` mavjud jadvallarga yangi ustun qo'shmaydi, shuning uchun
# `notification_logs` jadvalida `chat_id` ustuni yo'qligi sababli
# scheduler ishlamay qolgan edi. Bu buyruqlar Alembic migratsiyasida ham
# ishlatiladi (alembic/versions/0001_notification_logs_per_chat.py).
SCHEMA_UPGRADE_SQL: tuple[str, ...] = (
    "ALTER TABLE notification_logs "
    "ADD COLUMN IF NOT EXISTS chat_id BIGINT",
    "ALTER TABLE notification_logs "
    "ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE notification_logs "
    "ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMP WITH TIME ZONE",
    "CREATE INDEX IF NOT EXISTS ix_notification_logs_chat_id "
    "ON notification_logs (chat_id)",
    "CREATE INDEX IF NOT EXISTS ix_notification_logs_person_id "
    "ON notification_logs (person_id)",
    "ALTER TABLE notification_logs "
    "DROP CONSTRAINT IF EXISTS uq_person_birthday_year",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_person_birthday_year_chat'
        ) THEN
            ALTER TABLE notification_logs
            ADD CONSTRAINT uq_person_birthday_year_chat
            UNIQUE (person_id, birthday_year, chat_id);
        END IF;
    END
    $$;
    """,
    # --- Ko'p guruhli rejim: har bir inson bitta guruh jadvaliga tegishli ---
    "ALTER TABLE people ADD COLUMN IF NOT EXISTS group_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_people_group_id ON people (group_id)",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_people_group_id'
        ) THEN
            ALTER TABLE people
            ADD CONSTRAINT fk_people_group_id
            FOREIGN KEY (group_id) REFERENCES group_config (id)
            ON DELETE SET NULL;
        END IF;
    END
    $$;
    """,
    # Eski (guruhsiz) yozuvlar: bazada aynan bitta guruh bo'lsa, o'shanga
    # biriktiriladi. Bir nechta guruh bo'lsa, admin ularni /assign bilan
    # o'zi biriktiradi.
    """
    UPDATE people
    SET group_id = (SELECT id FROM group_config ORDER BY id LIMIT 1)
    WHERE group_id IS NULL
      AND (SELECT count(*) FROM group_config) = 1
    """,
    "ALTER TABLE auth_users "
    "ADD COLUMN IF NOT EXISTS selected_group_id INTEGER",
)


# Bazada birorta ham guruh bo'lmasa, .env dagi TARGET_GROUP_ID birinchi
# guruh sifatida qo'shiladi. Keyin guruhlar faqat bazadan boshqariladi.
SEED_TARGET_GROUP_SQL = """
INSERT INTO group_config (chat_id, title, timezone, reminder_time, is_active)
SELECT $1, 'Oila guruhi', $2, $3, true
WHERE NOT EXISTS (SELECT 1 FROM group_config)
"""


async def init_db() -> None:
    import app.models  # noqa: F401  (jadvallarni metadata'ga ro'yxatdan o'tkazadi)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

            if settings.target_group_id:
                await connection.exec_driver_sql(
                    SEED_TARGET_GROUP_SQL,
                    (
                        settings.target_group_id,
                        settings.timezone,
                        settings.birthday_reminder_time,
                    ),
                )

            for statement in SCHEMA_UPGRADE_SQL:
                await connection.exec_driver_sql(statement)

        logger.info("Database initialized successfully.")

    except Exception:
        logger.exception("Database initialization failed.")
        raise


async def close_db() -> None:
    try:
        await engine.dispose()
        logger.info("Database connections closed successfully.")

    except Exception:
        logger.exception("Failed to close database connections.")
        raise