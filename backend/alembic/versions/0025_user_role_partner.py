"""Роль partner в типе userrole (значение уже встречается в рабочей базе)

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-30
"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Идемпотентно и без изменения данных: в рабочей базе значение partner уже
    # есть (его добавили вручную), в свежей базе его нет — тогда добавляем.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type t
                JOIN pg_enum e ON e.enumtypid = t.oid
                WHERE t.typname = 'userrole' AND e.enumlabel = 'partner'
            ) THEN
                ALTER TYPE userrole ADD VALUE 'partner';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Postgres не умеет удалять значения enum, а существующие пользователи
    # с этой ролью должны остаться читаемыми.
    pass
