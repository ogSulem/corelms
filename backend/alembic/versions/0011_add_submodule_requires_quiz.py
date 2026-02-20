"""add submodule requires_quiz

Revision ID: 0011
Revises: 0010
Create Date: 2026-02-20

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submodules",
        sa.Column("requires_quiz", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("submodules", "requires_quiz")
