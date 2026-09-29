"""add send_client_reference_to_letter_provider column to service model

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-29 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0032'
down_revision = '0031'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('services', 'services_history'):
        op.add_column(
            table,
            sa.Column(
                'send_client_reference_to_letter_provider',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade():
    op.drop_column('services_history', 'send_client_reference_to_letter_provider')
    op.drop_column('services', 'send_client_reference_to_letter_provider')
