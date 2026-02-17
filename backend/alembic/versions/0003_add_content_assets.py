"""add content assets

Revision ID: 0003
Revises: 0002
Create Date: 2026-02-07

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("bucket", sa.String(length=200), nullable=False),
        sa.Column("object_key", sa.String(length=1000), nullable=False),
        sa.Column("original_filename", sa.String(length=400), nullable=False),
        sa.Column("mime_type", sa.String(length=200), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_content_assets_object_key", "content_assets", ["object_key"], unique=True)

    op.create_table(
        "submodule_asset_map",
        sa.Column(
            "submodule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("submodules.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("content_assets.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("submodule_id", "order", name="uq_submodule_asset_order"),
    )


def downgrade() -> None:
    op.drop_table("submodule_asset_map")

    op.drop_index("ix_content_assets_object_key", table_name="content_assets")
    op.drop_table("content_assets")
