"""add area_boundary column to organisation model

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-10 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0027'
down_revision = '0026'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('organisation', sa.Column('area_boundary', postgresql.JSONB, nullable=True))


def downgrade():
    op.drop_column('organisation', 'area_boundary')
