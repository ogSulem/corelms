"""add final_quiz_id to modules
 
Revision ID: 0005
Revises: 0004
Create Date: 2026-02-09 15:40:00.000000
 
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('modules', sa.Column('final_quiz_id', sa.UUID(), sa.ForeignKey('quizzes.id'), nullable=True))


def downgrade():
    op.drop_column('modules', 'final_quiz_id')
