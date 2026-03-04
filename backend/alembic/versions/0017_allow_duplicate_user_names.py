"""allow duplicate user names

Revision ID: 0017
Revises: 0016
Create Date: 2026-03-04

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users.name should not be unique; email is the primary unique identifier.
    # 0001 created ix_users_name as UNIQUE, we drop and recreate it as non-unique.
    op.drop_index("ix_users_name", table_name="users")
    op.create_index("ix_users_name", "users", ["name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_name", table_name="users")
    op.create_index("ix_users_name", "users", ["name"], unique=True)
