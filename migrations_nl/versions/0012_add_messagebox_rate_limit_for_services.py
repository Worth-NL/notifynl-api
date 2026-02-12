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


MBOX_MSG_LIMIT_COLUMN = "messagebox_message_limit"


def upgrade():
    op.add_column("services", sa.Column(MBOX_MSG_LIMIT_COLUMN, sa.BigInteger(), nullable=True))
    op.add_column("services_history", sa.Column(MBOX_MSG_LIMIT_COLUMN, sa.BigInteger(), nullable=True))


def downgrade():
    op.drop_column("services", MBOX_MSG_LIMIT_COLUMN)
    op.drop_column("services_history", MBOX_MSG_LIMIT_COLUMN)
