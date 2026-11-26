"""notification_logs: har bir guruh uchun alohida yozuv

Revision ID: 0001_logs_per_chat
Revises:
Create Date: 2026-11-26

Eski bazada ``notification_logs`` jadvalida ``chat_id`` ustuni yo'q edi
va ``(person_id, birthday_year)`` unikal cheklovi bir nechta guruhga
tabrik yuborishga to'sqinlik qilardi. Migratsiya idempotent: yangi
bazada ham, eski bazada ham xavfsiz ishlaydi.
"""

from alembic import op

from app.database import SCHEMA_UPGRADE_SQL


revision = "0001_logs_per_chat"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.database import Base
    import app.models  # noqa: F401

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    for statement in SCHEMA_UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE notification_logs "
        "DROP CONSTRAINT IF EXISTS uq_person_birthday_year_chat"
    )
    op.execute("ALTER TABLE notification_logs DROP COLUMN IF EXISTS last_attempt_at")
    op.execute("ALTER TABLE notification_logs DROP COLUMN IF EXISTS attempts")
    op.execute("ALTER TABLE notification_logs DROP COLUMN IF EXISTS chat_id")
