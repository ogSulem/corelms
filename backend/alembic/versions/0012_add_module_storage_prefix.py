"""add module storage_prefix

Revision ID: 0012
Revises: 0011
Create Date: 2026-02-22

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "modules",
        sa.Column("storage_prefix", sa.String(length=400), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("modules", "storage_prefix")
