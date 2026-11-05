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
import sqlalchemy as sa
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


def _index_state(name: str) -> str:
    """`missing` | `valid` | `invalid` — состояние индекса в текущей схеме."""
    row = op.get_bind().execute(
        sa.text(
            "SELECT i.indisvalid FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = :name AND n.nspname = current_schema()"
        ),
        {"name": name},
    ).first()
    if row is None:
        return "missing"
    return "valid" if row[0] else "invalid"


def _ensure_index(name: str, table: str, columns: str) -> None:
    """Создать индекс CONCURRENTLY, вылечив «полупостроенный» от прошлой попытки.

    Оборванный `CREATE INDEX CONCURRENTLY` (упал деплой, кончилось место, убили
    контейнер) оставляет индекс в состоянии INVALID: планировщик его не
    использует, а при записи он всё равно поддерживается — то есть место и
    время тратятся зря, и никто об этом не узнает. `IF NOT EXISTS` такой индекс
    молча пропустил бы, поэтому невалидный сначала удаляем.
    """
    with op.get_context().autocommit_block():
        if _index_state(name) == "invalid":
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
        if _index_state(name) == "missing":
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} ({columns})")


def upgrade():
    _ensure_index("ix_learning_events_user_created_at", "learning_events", "user_id, created_at")
    _ensure_index("ix_learning_events_created_at", "learning_events", "created_at")
    _ensure_index("ix_quiz_attempts_user_started_at", "quiz_attempts", "user_id, started_at")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_quiz_attempts_user_started_at")
    op.execute("DROP INDEX IF EXISTS ix_learning_events_created_at")
    op.execute("DROP INDEX IF EXISTS ix_learning_events_user_created_at")
