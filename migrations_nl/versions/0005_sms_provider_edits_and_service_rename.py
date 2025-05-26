"""SMS provider edits and service rename

Revision ID: 0005
Revises: 0004
Create Date: 2025-05-26 13:47:14.947483

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""UPDATE provider_details
               SET priority = 10
               WHERE identifier = 'spryng'
               """
               )

    op.execute("""UPDATE provider_details
               SET priority = 30, active = FALSE
               WHERE identifier = 'mmg'
               """
               )

    op.execute("""UPDATE provider_details
               SET supports_international = TRUE
               WHERE identifier = 'firetext'
               """
               )

    op.execute("""UPDATE services
               SET name = 'NotifyNl', normalised_service_name = 'notifynl', email_sender_local_part = 'notifynl'
               WHERE id = 'd6aa2c68-a2d9-4437-ab19-3ae8eb202553'
               """
               )


def downgrade():
    op.execute("""UPDATE provider_details
               SET priority = 30
               WHERE identifier = 'spryng'
               """
               )

    op.execute("""UPDATE provider_details
               SET priority = 10, active = TRUE
               WHERE identifier = 'mmg'
               """
               )

    op.execute("""UPDATE provider_details
               SET supports_international = FALSE
               WHERE identifier = 'firetext'
               """
               )

    op.execute("""UPDATE services
               SET name = 'GOV.UK Notify', normalised_service_name = 'gov.uk.notify', email_sender_local_part = 'gov.uk.notify'
               WHERE id = 'd6aa2c68-a2d9-4437-ab19-3ae8eb202553'
               """
               )
