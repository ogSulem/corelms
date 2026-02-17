"""remove manager role

Revision ID: 0008
Revises: 0007
Create Date: 2026-02-09

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Data migration: normalize managers to employees (product no longer supports manager).
    op.execute("UPDATE users SET role='employee' WHERE role='manager'")

    # 2) Replace enum type userrole to remove the 'manager' value.
    # Postgres does not support DROP VALUE for enums, so we recreate the type.
    op.execute("ALTER TYPE userrole RENAME TO userrole_old")
    op.execute("CREATE TYPE userrole AS ENUM ('employee', 'admin')")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::text::userrole")
    op.execute("DROP TYPE userrole_old")


def downgrade() -> None:
    # Re-add manager role to enum.
    op.execute("ALTER TYPE userrole RENAME TO userrole_old")
    op.execute("CREATE TYPE userrole AS ENUM ('employee', 'manager', 'admin')")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::text::userrole")
    op.execute("DROP TYPE userrole_old")
