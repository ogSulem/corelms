"""add module import_object_key

Revision ID: 0014
Revises: 0013
Create Date: 2026-02-28

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "modules",
        sa.Column("import_object_key", sa.String(length=1000), nullable=True),
    )
    op.create_index(
        "ix_modules_import_object_key",
        "modules",
        ["import_object_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_modules_import_object_key", table_name="modules")
    op.drop_column("modules", "import_object_key")
