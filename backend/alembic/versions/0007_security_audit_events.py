"""security audit events

Revision ID: 0007
Revises: 0006
Create Date: 2026-02-09

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("meta", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("ip", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_security_audit_events_actor_user_id", "security_audit_events", ["actor_user_id"], unique=False)
    op.create_index("ix_security_audit_events_target_user_id", "security_audit_events", ["target_user_id"], unique=False)
    op.create_index("ix_security_audit_events_event_type", "security_audit_events", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_security_audit_events_event_type", table_name="security_audit_events")
    op.drop_index("ix_security_audit_events_target_user_id", table_name="security_audit_events")
    op.drop_index("ix_security_audit_events_actor_user_id", table_name="security_audit_events")
    op.drop_table("security_audit_events")
