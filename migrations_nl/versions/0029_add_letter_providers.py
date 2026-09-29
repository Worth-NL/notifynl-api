"""add pingen and rest-endpoint letter providers

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-29 14:00:00.000000

Letter providers are chosen per organisation (organisation_letter_provider), not by priority. Their priority is
set above dvla's (50) so code that still picks "the first letter provider by priority" keeps choosing dvla.
"""
import uuid

from alembic import op
from sqlalchemy import text

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None

PROVIDERS = [
    # (identifier, display_name, priority, supports_international)
    ('pingen', 'Pingen', 60, True),
    ('rest-endpoint', 'REST-endpoint', 70, True),
]


def upgrade():
    for identifier, display_name, priority, supports_international in PROVIDERS:
        provider_id = str(uuid.uuid4())
        for table in ('provider_details', 'provider_details_history'):
            op.execute(text(
                f"""INSERT INTO {table}
                (id, display_name, identifier, priority, notification_type, active, version, supports_international)
                VALUES ('{provider_id}', '{display_name}', '{identifier}', {priority}, 'letter', true, 1,
                {str(supports_international).lower()})
                """
            ))


def downgrade():
    for identifier, *_ in PROVIDERS:
        op.execute(text(f"DELETE FROM provider_details WHERE identifier = '{identifier}'"))
        op.execute(text(f"DELETE FROM provider_details_history WHERE identifier = '{identifier}'"))
