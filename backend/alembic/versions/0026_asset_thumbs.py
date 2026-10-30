"""Превью файлов (картинка и кадр видео) для списков материалов."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    uid = postgresql.UUID(as_uuid=True)
    op.create_table("asset_thumbs",
        sa.Column("id", uid, primary_key=True),
        sa.Column("asset_id", uid, sa.ForeignKey("content_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("source_bucket", sa.String(200), nullable=False),
        sa.Column("source_object_key", sa.String(1000), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False, server_default="image"),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.String(500)),
        sa.Column("bucket", sa.String(200)),
        sa.Column("object_key", sa.String(1000)),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("asset_id", "source_version", name="uq_asset_thumb_version"))
    op.create_index("ix_asset_thumbs_asset_id", "asset_thumbs", ["asset_id"])
    op.create_index("ix_asset_thumb_state", "asset_thumbs", ["state", "updated_at"])


def downgrade():
    op.drop_index("ix_asset_thumb_state", table_name="asset_thumbs")
    op.drop_index("ix_asset_thumbs_asset_id", table_name="asset_thumbs")
    op.drop_table("asset_thumbs")
