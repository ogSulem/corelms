"""add user email

Revision ID: 0016
Revises: 0015
Create Date: 2026-03-02

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email", sa.String(length=320), nullable=True),
    )

    # Case-insensitive uniqueness for non-null emails.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_ci ON users (lower(email)) WHERE email IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_email_ci")
    op.drop_column("users", "email")
