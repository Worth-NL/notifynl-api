"""add mark_delivered_on_acceptance column to organisation_letter_provider

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-19 14:00:00.000000

Whether a letter counts as delivered once the organisation's REST endpoint accepts it, for endpoints that never report
back. Expand-only: the previous release ignores the column, and its default keeps today's behaviour.
"""
from alembic import op
import sqlalchemy as sa

revision = '0037'
down_revision = '0036'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'organisation_letter_provider',
        sa.Column('mark_delivered_on_acceptance', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column('organisation_letter_provider', 'mark_delivered_on_acceptance')
