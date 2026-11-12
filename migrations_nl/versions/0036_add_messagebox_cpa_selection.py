"""add messagebox_cpa_selection tables

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-10 12:00:00.000000

Which ebms-core CPA messagebox notifications are sent under, per purpose (`live` for normal keys, `team` for team keys
to Logius pre-production), plus the history of every selection. Expand-only: the previous release ignores both tables.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'messagebox_cpa_selection',
        sa.Column('purpose', sa.String(length=16), primary_key=True),
        sa.Column('cpa_id', sa.String(), nullable=False),
        sa.Column('from_party_id', sa.String(), nullable=False),
        sa.Column('to_party_id', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('message_type', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.CheckConstraint("purpose IN ('live', 'team')", name='ck_messagebox_cpa_selection_purpose'),
    )
    op.create_table(
        'messagebox_cpa_selection_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('purpose', sa.String(length=16), nullable=False),
        sa.Column('cpa_id', sa.String(), nullable=False),
        sa.Column('from_party_id', sa.String(), nullable=False),
        sa.Column('to_party_id', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('message_type', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
    )
    op.create_index(
        op.f('ix_messagebox_cpa_selection_history_purpose'), 'messagebox_cpa_selection_history', ['purpose']
    )


def downgrade():
    op.drop_index(op.f('ix_messagebox_cpa_selection_history_purpose'), table_name='messagebox_cpa_selection_history')
    op.drop_table('messagebox_cpa_selection_history')
    op.drop_table('messagebox_cpa_selection')
