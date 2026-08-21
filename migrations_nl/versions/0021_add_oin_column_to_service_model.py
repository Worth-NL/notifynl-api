"""add oin column to service model

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-13 09:05:54.995183

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('services', sa.Column('oin', sa.String(length=20), nullable=True))
    op.add_column('services_history', sa.Column('oin', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('services_history', 'oin')
    op.drop_column('services', 'oin')
