"""set netherlands postage crown state

Revision ID: 0017
Revises: 0016
Create Date: 2026-03-12 11:12:25.466002

"""
from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


POST_CLASS = 'netherlands'


letter_rate_update = text("""
UPDATE letter_rates
SET crown = :crown
WHERE post_class = :post_class""")


def upgrade():
    op.execute(
        letter_rate_update.bindparams(
            post_class = POST_CLASS,
            crown = True
        )
    )


def downgrade():
    op.execute(
        letter_rate_update.bindparams(
            post_class = POST_CLASS,
            crown = False
        )
    )
