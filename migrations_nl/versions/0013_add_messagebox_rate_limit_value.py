"""add messagebox rate limit default value and non-nullable prop

Revision ID: 0013
Revises: 0012
Create Date: 2026-02-12 10:55:53.539802

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


MBOX_MSG_LIMIT_COLUMN = "messagebox_message_limit"
SVC_TABLES = ["services", "services_history"]


def upgrade():
    for service_table in SVC_TABLES:
        op.execute(f"UPDATE {service_table} SET {MBOX_MSG_LIMIT_COLUMN} = 50")
        op.alter_column(service_table, sa.Column(MBOX_MSG_LIMIT_COLUMN, sa.BigInteger(), nullable=False))


def downgrade():
    for service_table in SVC_TABLES:
        op.alter_column(service_table, sa.Column(MBOX_MSG_LIMIT_COLUMN, sa.BigInteger(), nullable=True))
        op.execute(f"UPDATE {service_table} SET {MBOX_MSG_LIMIT_COLUMN} = NULL")
