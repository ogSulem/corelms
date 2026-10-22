"""Lesson presentation, original-preserving media and a reversible sales library."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    uid = postgresql.UUID(as_uuid=True)
    op.add_column("submodules", sa.Column("presentation_mode", sa.String(16), nullable=False, server_default="auto"))
    op.add_column("submodules", sa.Column("primary_asset_id", uid, nullable=True))
    op.create_foreign_key("fk_submodule_primary_asset", "submodules", "content_assets", ["primary_asset_id"], ["id"], ondelete="SET NULL")
    op.add_column("questions", sa.Column("position", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("modules", sa.Column("final_quiz_enabled", sa.Boolean(), nullable=False, server_default="true"))
    op.create_table("asset_renditions",
        sa.Column("id", uid, primary_key=True), sa.Column("asset_id", uid, sa.ForeignKey("content_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False), sa.Column("source_bucket", sa.String(200), nullable=False),
        sa.Column("source_object_key", sa.String(1000), nullable=False), sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("job_id", sa.String(64)), sa.Column("run_token", sa.String(64)), sa.Column("error", sa.String(1000)),
        sa.Column("bucket", sa.String(200)), sa.Column("object_key", sa.String(1000)), sa.Column("mime_type", sa.String(200)),
        sa.Column("size_bytes", sa.BigInteger()), sa.Column("checksum_sha256", sa.String(64)), sa.Column("text_content", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("asset_id", "source_version", name="uq_asset_rendition_version"))
    op.create_index("ix_asset_renditions_asset_id", "asset_renditions", ["asset_id"])
    op.create_index("ix_asset_rendition_dispatch", "asset_renditions", ["state", "updated_at"])
    op.create_table("sales_sections", sa.Column("name", sa.String(20), primary_key=True), sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.bulk_insert(sa.table("sales_sections", sa.column("name", sa.String())), [{"name": "photos"}, {"name": "catalogs"}])
    op.create_table("sales_entries", sa.Column("id", uid, primary_key=True),
        sa.Column("section", sa.String(20), sa.ForeignKey("sales_sections.name"), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False), sa.Column("name", sa.String(400), nullable=False),
        sa.Column("identity_key", sa.String(64), nullable=False, unique=True), sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("asset_id", uid, sa.ForeignKey("content_assets.id"), unique=True), sa.Column("legacy_key", sa.String(1000), unique=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"))
    op.create_index("ix_sales_entries_directory", "sales_entries", ["section", "path", "is_archived"])
    op.create_index("ix_sales_entries_section", "sales_entries", ["section"])
    op.create_index("ix_sales_entries_is_archived", "sales_entries", ["is_archived"])


def downgrade():
    op.drop_table("sales_entries")
    op.drop_table("sales_sections")
    op.drop_table("asset_renditions")
    op.drop_column("questions", "position")
    op.drop_column("modules", "final_quiz_enabled")
    op.drop_constraint("fk_submodule_primary_asset", "submodules", type_="foreignkey")
    op.drop_column("submodules", "primary_asset_id")
    op.drop_column("submodules", "presentation_mode")
