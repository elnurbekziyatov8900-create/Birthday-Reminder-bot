"""people: har bir inson bitta guruh jadvaliga tegishli

Revision ID: 0002_people_per_group
Revises: 0001_logs_per_chat
Create Date: 2026-11-26

``people.group_id`` (group_config.id ga FK) va
``auth_users.selected_group_id`` ustunlarini qo'shadi. SQL idempotent.
"""

from alembic import op

from app.database import SCHEMA_UPGRADE_SQL


revision = "0002_people_per_group"
down_revision = "0001_logs_per_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in SCHEMA_UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE auth_users DROP COLUMN IF EXISTS selected_group_id")
    op.execute("ALTER TABLE people DROP CONSTRAINT IF EXISTS fk_people_group_id")
    op.execute("DROP INDEX IF EXISTS ix_people_group_id")
    op.execute("ALTER TABLE people DROP COLUMN IF EXISTS group_id")
