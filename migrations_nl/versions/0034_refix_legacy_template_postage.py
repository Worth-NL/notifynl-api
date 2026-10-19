"""fix legacy template postage values written since 0020

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-19 10:00:00.000000

"""
from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '0034'
down_revision = '0033'
branch_labels = None
depends_on = None


VALID_POSTAGE_TYPES = ('netherlands', 'europe', 'rest-of-world')
NETHERLANDS = 'netherlands'

# Re-runs 0020 for templates written since. The API rejects legacy postage, but the
# database has no check constraint (upstream dropped it in 0321), so rows written around
# the API, e.g. directly through the models, can still hold upstream's UK 'first'/'second'.
# As in 0020, notifications/notification_history are left out (large, no index on postage).
tables = ('templates', 'templates_history')

update_postage_sql = """
    UPDATE {}
    SET postage = :postage
    WHERE postage NOT IN :valid_postage_types"""


def upgrade():
    for table in tables:
        op.execute(
            text(update_postage_sql.format(table)).bindparams(
                postage=NETHERLANDS,
                valid_postage_types=VALID_POSTAGE_TYPES,
            )
        )


def downgrade():
    # Original per-row values ('first' vs 'second') aren't recoverable.
    pass
