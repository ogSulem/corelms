"""add superadmin role

Revision ID: 0020
Revises: 0019
Create Date: 2026-03-20

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new enum value to existing Postgres enum.
    # This is safe and fast.
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'superadmin'")


def downgrade() -> None:
    # Postgres does not support DROP VALUE for enums.
    # Recreate type without 'superadmin'.
    op.execute("ALTER TYPE userrole RENAME TO userrole_old")
    op.execute("CREATE TYPE userrole AS ENUM ('employee', 'admin')")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::text::userrole")
    op.execute("DROP TYPE userrole_old")
