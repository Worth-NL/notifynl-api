"""Extra branding options

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-06 13:53:29.749172

"""
from alembic import op
from sqlalchemy import Column, INTEGER, String
from app.models import EmailBranding


# revision identifiers, used by Alembic.
revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


COLUMN_ALIGNMENT = "alignment"
COLUMN_HEIGHT = "height"


def upgrade():
    op.add_column(
        EmailBranding.__tablename__,
        Column(
            COLUMN_ALIGNMENT,
            String(6),
            nullable=False,
            server_default="left"
        )
    )

    op.add_column(
        EmailBranding.__tablename__,
        Column(
            COLUMN_HEIGHT,
            INTEGER,
            nullable=True
        )
    )


def downgrade():
    op.drop_column(
        EmailBranding.__tablename__,
        column_name=COLUMN_ALIGNMENT
    )

    op.drop_column(
        EmailBranding.__tablename__,
        column_name=COLUMN_HEIGHT
    )
