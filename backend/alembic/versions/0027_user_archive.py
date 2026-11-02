"""Архив учётных записей: уволенного партнёра можно убрать из списков, не теряя историю обучения.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    # NOT NULL + server_default: на работающей базе колонка добавляется без
    # переписывания таблицы и без единой NULL-строки.
    op.add_column(
        "users",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_users_is_archived", "users", ["is_archived"])

    # Кто и когда ушёл в архив — нужно для разбора, поэтому пишем в аудит.
    op.execute(
        """
        COMMENT ON COLUMN users.is_archived IS
        'Учётная запись в архиве: вход запрещён, из списков скрыта, история обучения сохранена'
        """
    )


def downgrade():
    op.drop_index("ix_users_is_archived", table_name="users")
    op.drop_column("users", "is_archived")
