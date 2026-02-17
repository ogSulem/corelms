"""add submodule content_object_key

Revision ID: 0009
Revises: 0008
Create Date: 2026-02-11

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submodules",
        sa.Column("content_object_key", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("submodules", "content_object_key")
