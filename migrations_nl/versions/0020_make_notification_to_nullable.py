"""make notifications.to nullable, so the messagebox BSN can be wiped once a
notification reaches a permanent end state

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('notifications', 'to', existing_type=sa.String(), nullable=True)


def downgrade():
    # Will fail if any row has `to` set to NULL (e.g. a messagebox notification
    # whose BSN has already been wiped after reaching a terminal state) --
    # that data is intentionally gone and cannot be restored.
    op.alter_column('notifications', 'to', existing_type=sa.String(), nullable=False)
