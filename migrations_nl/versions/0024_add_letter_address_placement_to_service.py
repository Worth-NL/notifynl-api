"""add letter_address_placement column to service model

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-12 10:52:58.921551

"""
from alembic import op
import sqlalchemy as sa

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'services',
        sa.Column('letter_address_placement', sa.String(length=5), nullable=True, server_default='60mm'),
    )
    op.add_column(
        'services_history',
        sa.Column('letter_address_placement', sa.String(length=5), nullable=True, server_default='60mm'),
    )


def downgrade():
    op.drop_column('services_history', 'letter_address_placement')
    op.drop_column('services', 'letter_address_placement')
