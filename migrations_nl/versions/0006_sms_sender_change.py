"""SMS sender change

Revision ID: 0006
Revises: 0005
Create Date: 2025-05-26 14:17:22.480590

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""UPDATE service_sms_senders
               SET sms_sender = 'NOTIFYNL'
               WHERE id = '286d6176-adbe-7ea7-ba26-b7606ee5e2a4'
               """)


def downgrade():
    op.execute("""UPDATE service_sms_senders
               SET sms_sender = 'GOVUK'
               WHERE id = '286d6176-adbe-7ea7-ba26-b7606ee5e2a4'
               """)
