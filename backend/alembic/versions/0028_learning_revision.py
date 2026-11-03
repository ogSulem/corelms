"""Отдельная ревизия «того, что видит ученик»: переименование модуля больше не
рисует всем отметку «есть обновления».

content_revision остаётся токеном редактора (меняется на любое сохранение и
защищает от перезаписи из второй вкладки). learning_revision растёт только
когда меняется сам учебный контент: уроки, файлы, тесты, публикация.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    # NOT NULL + server_default: колонка добавляется без переписывания таблицы.
    op.add_column(
        "modules",
        sa.Column("learning_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    # Выравниваем с текущей ревизией, чтобы ни у кого не появилось ложное
    # «есть обновления» сразу после обновления платформы.
    op.execute("UPDATE modules SET learning_revision = content_revision")
    op.execute(
        """
        COMMENT ON COLUMN modules.learning_revision IS
        'Ревизия учебного контента для ученика: растёт при изменении уроков, файлов, тестов и публикации'
        """
    )


def downgrade():
    op.drop_column("modules", "learning_revision")
