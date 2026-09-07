"""fix legacy postage values

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-31 09:00:00.000000

"""
from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


VALID_POSTAGE_TYPES = ('netherlands', 'europe', 'rest-of-world')
NETHERLANDS = 'netherlands'

# 'first' and 'second' are upstream's old UK domestic postage tiers, both of
# which map onto our single domestic tier, 'netherlands'. Only templates are
# covered here -- notifications/notification_history can be multi-million-row
# tables with no index on postage, and fixing already-sent letters' historical
# postage label isn't worth an unbatched full-table scan in a shared env.
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
