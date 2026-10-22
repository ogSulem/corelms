"""Non-destructive content updates, file versions and durable achievements.

Revision ID: 0021
Revises: 0020
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uid = postgresql.UUID(as_uuid=True)
    op.add_column("quiz_attempts", sa.Column("session_id", sa.String(64), nullable=True))
    op.add_column("quiz_attempts", sa.Column("xp_awarded", sa.Integer(), nullable=False, server_default="0"))
    op.create_unique_constraint("uq_quiz_attempts_session_id", "quiz_attempts", ["session_id"])
    op.add_column("modules", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("modules", sa.Column("content_revision", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_modules_is_archived", "modules", ["is_archived"])
    op.add_column("submodules", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("submodules", sa.Column("source_path", sa.String(1000), nullable=True))
    op.create_index("ix_submodules_is_archived", "submodules", ["is_archived"])
    op.add_column("content_assets", sa.Column("module_id", uid, sa.ForeignKey("modules.id"), nullable=True))
    op.add_column("content_assets", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("content_assets", sa.Column("source_path", sa.String(1000), nullable=True))
    op.add_column("content_assets", sa.Column("order", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_content_assets_module_id", "content_assets", ["module_id"])
    op.create_index("ix_content_assets_is_archived", "content_assets", ["is_archived"])

    # Ownership must not depend on a filename or on parsing a UUID from an S3 key.
    # Only assign unambiguous lesson assets; genuinely shared legacy files still use links.
    op.execute(r"""
        UPDATE content_assets a SET module_id = x.module_id
        FROM (
            SELECT sam.asset_id, MIN(s.module_id::text)::uuid AS module_id
            FROM submodule_asset_map sam JOIN submodules s ON s.id = sam.submodule_id
            GROUP BY sam.asset_id HAVING COUNT(DISTINCT s.module_id) = 1
        ) x WHERE a.id = x.asset_id
    """)
    op.execute(r"""
        UPDATE content_assets a SET module_id = m.id
        FROM modules m
        WHERE a.module_id IS NULL
          AND starts_with(a.object_key, RTRIM(COALESCE(NULLIF(m.storage_prefix, ''), 'modules/' || m.id::text), '/') || '/_module/')
    """)

    op.create_table(
        "module_completions",
        sa.Column("user_id", uid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("module_id", uid, sa.ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "lesson_quiz_versions",
        sa.Column("quiz_id", uid, sa.ForeignKey("quizzes.id"), primary_key=True),
        sa.Column("submodule_id", uid, sa.ForeignKey("submodules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_lesson_quiz_versions_submodule_id", "lesson_quiz_versions", ["submodule_id"])
    op.execute("INSERT INTO lesson_quiz_versions (quiz_id, submodule_id, created_at) SELECT quiz_id, id, NOW() FROM submodules")

    # Backfill achievements BEFORE any content can change. Legacy read metadata may
    # be either 'read' or JSON; do not cast arbitrary historical strings to jsonb.
    op.execute(r"""
        INSERT INTO module_completions (user_id, module_id, completed_at, content_revision)
        SELECT u.id, m.id, NOW(), 1 FROM users u CROSS JOIN modules m
        WHERE EXISTS (SELECT 1 FROM submodules s WHERE s.module_id=m.id AND NOT s.is_folder)
          AND NOT EXISTS (
            SELECT 1 FROM submodules s WHERE s.module_id=m.id AND NOT s.is_folder AND (
              (s.requires_quiz AND NOT EXISTS (
                SELECT 1 FROM quiz_attempts qa WHERE qa.user_id=u.id AND qa.quiz_id=s.quiz_id AND qa.passed
              )) OR (NOT s.requires_quiz AND NOT EXISTS (
                SELECT 1 FROM learning_events le WHERE le.user_id=u.id AND le.ref_id=s.id
                  AND le.type='submodule_opened' AND (le.meta='read' OR le.meta ~ '"action"\s*:\s*"read"')
              ))
            )
          )
          AND (m.final_quiz_id IS NULL OR NOT EXISTS (
              SELECT 1 FROM submodules s WHERE s.module_id=m.id AND NOT s.is_folder AND s.requires_quiz
          ) OR EXISTS (
              SELECT 1 FROM quiz_attempts qa WHERE qa.user_id=u.id AND qa.quiz_id=m.final_quiz_id AND qa.passed
          ))
    """)

    op.create_table(
        "asset_revisions",
        sa.Column("id", uid, primary_key=True),
        sa.Column("asset_id", uid, sa.ForeignKey("content_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("bucket", sa.String(200), nullable=False),
        sa.Column("object_key", sa.String(1000), nullable=False),
        sa.Column("original_filename", sa.String(400), nullable=False),
        sa.Column("mime_type", sa.String(200), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", uid, nullable=True),
        sa.UniqueConstraint("asset_id", "version", name="uq_asset_revision"),
    )
    op.create_index("ix_asset_revisions_asset_id", "asset_revisions", ["asset_id"])


def downgrade() -> None:
    op.drop_constraint("uq_quiz_attempts_session_id", "quiz_attempts", type_="unique")
    op.drop_column("quiz_attempts", "session_id")
    op.drop_column("quiz_attempts", "xp_awarded")
    op.drop_table("asset_revisions")
    op.drop_table("lesson_quiz_versions")
    op.drop_table("module_completions")
    for table, columns in {
        "content_assets": ["module_id", "is_archived", "source_path", "order"],
        "submodules": ["is_archived", "source_path"],
        "modules": ["is_archived", "content_revision"],
    }.items():
        for column in columns:
            if column in {"module_id", "is_archived"}:
                op.drop_index(f"ix_{table}_{column}", table_name=table)
            op.drop_column(table, column)
