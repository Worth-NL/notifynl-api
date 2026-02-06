"""messagebox service permission type

Revision ID: 0011
Revises: 0010
Create Date: 2026-01-23 16:29:30.127546

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


TABLE = "service_permission_types"
MESSAGEBOX_TYPE = "messagebox"


def upgrade():
    op.execute(
        sa.text(
            f"INSERT INTO {TABLE} (name) VALUES ('{MESSAGEBOX_TYPE}')"
        )
    )


def downgrade():
    op.execute(
        sa.text(
            f"DELETE FROM service_permissions WHERE permission = '{MESSAGEBOX_TYPE}'"
        )
    )
    
    op.execute(
        sa.text(
            f"DELETE FROM {TABLE} WHERE permission = '{MESSAGEBOX_TYPE}'"
        )
    )