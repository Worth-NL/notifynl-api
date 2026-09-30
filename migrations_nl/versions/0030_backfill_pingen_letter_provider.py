"""assign pingen as letter provider to every existing organisation

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-29 14:00:00.000000

Pingen is the default letter provider. Organisations using their own REST endpoint switch to it in the admin UI.
"""
from alembic import op
from sqlalchemy import text

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None

BACKFILL_PINGEN_LETTER_PROVIDER = """
    INSERT INTO organisation_letter_provider (organisation_id, provider_details_id, address_placement, created_at)
    SELECT organisation.id, provider_details.id, '60mm', now()
    FROM organisation
    JOIN provider_details ON provider_details.identifier = 'pingen' AND provider_details.notification_type = 'letter'
    ON CONFLICT (organisation_id) DO NOTHING
"""


def upgrade():
    op.execute(text(BACKFILL_PINGEN_LETTER_PROVIDER))


def downgrade():
    op.execute(text(
        """DELETE FROM organisation_letter_provider
        USING provider_details
        WHERE provider_details.id = organisation_letter_provider.provider_details_id
        AND provider_details.identifier = 'pingen'
        AND organisation_letter_provider.endpoint_url IS NULL
        AND organisation_letter_provider.updated_by_id IS NULL
        """
    ))
