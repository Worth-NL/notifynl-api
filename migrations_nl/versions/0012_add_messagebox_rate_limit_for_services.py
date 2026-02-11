"""add messagebox rate limit for services

Revision ID: 0012
Revises: 0011
Create Date: 2026-02-11 09:25:57.613343

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("services", sa.Column("messagebox_message_limit", sa.BigInteger(), nullable=True))


def downgrade():
    op.drop_column("services_history", "messagebox_message_limit")
