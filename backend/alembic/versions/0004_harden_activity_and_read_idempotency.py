"""harden activity and read idempotency

Revision ID: 0004
Revises: 0003
Create Date: 2026-02-08

"""

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Enterprise-streak source of truth
    op.add_column(
        "users",
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index("ix_users_last_activity_at", "users", ["last_activity_at"], unique=False)

    # Backfill: use latest learning event if present
    op.execute(
        """
        UPDATE users u
        SET last_activity_at = sub.max_created_at
        FROM (
            SELECT user_id, MAX(created_at) AS max_created_at
            FROM learning_events
            GROUP BY user_id
        ) sub
        WHERE sub.user_id = u.id
        """
    )

    # 2) Idempotency for READ confirmations at DB level
    # Cleanup potential duplicates before enforcing uniqueness
    op.execute(
        """
        DELETE FROM learning_events le
        USING learning_events le2
        WHERE le.user_id = le2.user_id
          AND le.type = le2.type
          AND le.ref_id = le2.ref_id
          AND COALESCE(le.meta, '') = COALESCE(le2.meta, '')
          AND le.type = 'submodule_opened'
          AND le.meta = 'read'
          AND le.id <> le2.id
          AND le.created_at >= le2.created_at
        """
    )

    op.create_index(
        "ux_learning_events_read_once",
        "learning_events",
        ["user_id", "ref_id"],
        unique=True,
        postgresql_where=sa.text("type = 'submodule_opened' AND meta = 'read'"),
    )


def downgrade() -> None:
    op.drop_index("ux_learning_events_read_once", table_name="learning_events")

    op.drop_index("ix_users_last_activity_at", table_name="users")
    op.drop_column("users", "last_activity_at")
