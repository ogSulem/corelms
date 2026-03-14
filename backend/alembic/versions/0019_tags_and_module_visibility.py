"""tags and module visibility

Revision ID: 0019
Revises: 0018
Create Date: 2026-03-14

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "modules",
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="public"),
    )
    op.create_index("ix_modules_visibility", "modules", ["visibility"], unique=False)

    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tags_name", "tags", ["name"], unique=True)

    op.create_table(
        "user_tag_map",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True, nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tags.id"), primary_key=True, nullable=False),
    )
    op.create_index("ix_user_tag_map_user_id", "user_tag_map", ["user_id"], unique=False)
    op.create_index("ix_user_tag_map_tag_id", "user_tag_map", ["tag_id"], unique=False)

    op.create_table(
        "module_tag_map",
        sa.Column("module_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("modules.id"), primary_key=True, nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tags.id"), primary_key=True, nullable=False),
    )
    op.create_index("ix_module_tag_map_module_id", "module_tag_map", ["module_id"], unique=False)
    op.create_index("ix_module_tag_map_tag_id", "module_tag_map", ["tag_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_module_tag_map_tag_id", table_name="module_tag_map")
    op.drop_index("ix_module_tag_map_module_id", table_name="module_tag_map")
    op.drop_table("module_tag_map")

    op.drop_index("ix_user_tag_map_tag_id", table_name="user_tag_map")
    op.drop_index("ix_user_tag_map_user_id", table_name="user_tag_map")
    op.drop_table("user_tag_map")

    op.drop_index("ix_tags_name", table_name="tags")
    op.drop_table("tags")

    op.drop_index("ix_modules_visibility", table_name="modules")
    op.drop_column("modules", "visibility")
