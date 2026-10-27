"""add letter_provider_pin table

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-27 12:00:00.000000

The print provider (and, for a REST endpoint, the URL) a letter is being sent to, written before the send and kept
while the provider may have accepted it. A later attempt then can't send the letter to another provider as well. No
foreign key to notifications, like letter_provider_reference.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0035'
down_revision = '0034'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'letter_provider_pin',
        sa.Column('notification_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('endpoint_url', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )


def downgrade():
    op.drop_table('letter_provider_pin')
