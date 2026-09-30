"""add letter_provider_reference table

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-29 14:00:00.000000

Maps a letter to the id the print provider gave it (e.g. Pingen's letter id), for correlating provider webhooks and
resuming retries. No foreign key to notifications: the mapping must survive the move to notification_history.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0031'
down_revision = '0030'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'letter_provider_reference',
        sa.Column('notification_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('provider_reference', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('provider', 'provider_reference', name='uix_letter_provider_reference'),
    )


def downgrade():
    op.drop_table('letter_provider_reference')
