"""add detailed_status_code and messagebox_stadium columns to notification models

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-16 14:29:24.809554

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('notifications', sa.Column('detailed_status_code', sa.String(), nullable=True))
    op.add_column('notifications', sa.Column('messagebox_stadium', sa.String(), nullable=True))
    op.add_column('notification_history', sa.Column('detailed_status_code', sa.String(), nullable=True))
    op.add_column('notification_history', sa.Column('messagebox_stadium', sa.String(), nullable=True))


def downgrade():
    op.drop_column('notification_history', 'messagebox_stadium')
    op.drop_column('notification_history', 'detailed_status_code')
    op.drop_column('notifications', 'messagebox_stadium')
    op.drop_column('notifications', 'detailed_status_code')
