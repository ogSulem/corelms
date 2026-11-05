"""Индексы под журнал обучения и попытки тестов.

Все «горячие» чтения этих таблиц фильтруют по пользователю и сортируют по
времени: лента активности, результаты, история попыток. Отдельных индексов по
`user_id` и `created_at` не хватало — база сортировала выборку целиком.

Индексы создаются `CONCURRENTLY`: на работающей платформе обычный `CREATE INDEX`
блокирует запись в таблицу на всё время построения.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-05
"""
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def _concurrently(sql: str) -> None:
    # CONCURRENTLY нельзя выполнять внутри транзакции: alembic даёт для этого
    # autocommit-блок. На SQLite миграции не применяются (тесты строят схему из
    # моделей), поэтому достаточно диалекта PostgreSQL.
    with op.get_context().autocommit_block():
        op.execute(sql)


def upgrade():
    _concurrently("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_learning_events_user_created_at "
                  "ON learning_events (user_id, created_at)")
    _concurrently("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_learning_events_created_at "
                  "ON learning_events (created_at)")
    _concurrently("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_quiz_attempts_user_started_at "
                  "ON quiz_attempts (user_id, started_at)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_quiz_attempts_user_started_at")
    op.execute("DROP INDEX IF EXISTS ix_learning_events_created_at")
    op.execute("DROP INDEX IF EXISTS ix_learning_events_user_created_at")
