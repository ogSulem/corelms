"""add submodule folder fields

Revision ID: 0015
Revises: 0014
Create Date: 2026-02-28

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submodules",
        sa.Column("is_folder", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "submodules",
        sa.Column("outline_path", sa.String(length=1000), nullable=True),
    )
    op.create_index(
        "ix_submodules_module_id_outline_path",
        "submodules",
        ["module_id", "outline_path"],
        unique=False,
    )

    # Remove server default for cleanliness (keep application default).
    op.alter_column("submodules", "is_folder", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_submodules_module_id_outline_path", table_name="submodules")
    op.drop_column("submodules", "outline_path")
    op.drop_column("submodules", "is_folder")
