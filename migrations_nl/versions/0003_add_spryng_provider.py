"""Add Spryng provider

Revision ID: 0003
Revises: 0002
Create Date: 2025-04-29 12:48:25.810290

"""

import uuid

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

identifier = "spryng"
provider_id = str(uuid.uuid4())


def upgrade():
    op.execute(
        f"""INSERT INTO provider_details
        (id, display_name, identifier, priority, notification_type, active, version, supports_international)
        VALUES ('{provider_id}', '{identifier.capitalize()}', '{identifier}', 30, 'sms', true, 1, true)
        """
    )


def downgrade():
    op.execute(f"DELETE FROM provider_details WHERE identifier = '{identifier}'")
