"""Preserve manual lesson text and distinguish source hashes from file bytes.

Revision ID: 0022
Revises: 0021
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    # Old text may contain manual edits. Do not guess that it is replaceable.
    op.add_column("submodules", sa.Column("content_mode", sa.String(16), nullable=False, server_default="manual"))
    op.add_column("submodules", sa.Column("content_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("content_assets", sa.Column("source_checksum_sha256", sa.String(64), nullable=True))
    # Never infer a source digest from stored bytes: even an MP4-to-MP4 codec
    # conversion or a manual replacement can change them. The first successful
    # reimport establishes the source baseline; physical-byte equality still
    # avoids unnecessary file versions for unchanged legacy files.
    op.create_table(
        "lesson_revisions",
        sa.Column("id", uid, primary_key=True),
        sa.Column("submodule_id", uid, sa.ForeignKey("submodules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_mode", sa.String(16), nullable=False),
        sa.Column("content_object_key", sa.String(1000), nullable=True),
        sa.Column("bucket", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", uid, nullable=True),
        sa.UniqueConstraint("submodule_id", "version", name="uq_lesson_revision"),
    )
    op.create_index("ix_lesson_revisions_submodule_id", "lesson_revisions", ["submodule_id"])


def downgrade() -> None:
    op.drop_table("lesson_revisions")
    op.drop_column("content_assets", "source_checksum_sha256")
    op.drop_column("submodules", "content_version")
    op.drop_column("submodules", "content_mode")
