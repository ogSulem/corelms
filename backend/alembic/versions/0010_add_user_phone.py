"""add user phone

Revision ID: 0010
Revises: 0009
Create Date: 2026-02-17

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("phone", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "phone")
