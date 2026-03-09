"""letter rate change

Revision ID: 0016
Revises: 0015
Create Date: 2026-03-09 10:11:07.534511

"""
from alembic import op
from sqlalchemy import text
from datetime import datetime, timezone, timedelta
from uuid import uuid4


# revision identifiers, used by Alembic.
revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


POST_CLASS = 'netherlands'
YESTERDAY = datetime.now(timezone.utc) - timedelta(weeks=52)


def upgrade():
    letter_rate_update = text("""
    INSERT INTO letter_rates
        (id, start_date, end_date, sheet_count, rate, crown, post_class)
    VALUES
        (:id, :start_date, :end_date, :sheet_count, :rate, :crown, :post_class)""")

    for sheet_count in range(1, 6):
        op.execute(
            letter_rate_update.bindparams(
                id = uuid4(),
                start_date = YESTERDAY,
                end_date = None,
                sheet_count = sheet_count,
                rate = float(0),
                crown = False,
                post_class = POST_CLASS
            )
        )


def downgrade():
    letter_rate_delete = text("""
        DELETE FROM letter_rates
        WHERE post_class = :post_class""")

    op.execute(
        letter_rate_delete.bindparams(
            post_class = POST_CLASS
        )
    )
