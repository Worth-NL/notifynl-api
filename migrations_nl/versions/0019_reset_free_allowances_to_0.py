"""reset free allowances to 0

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-13 00:00:00.000000

NotifyNL has no free SMS allowances (see 0007_set_free_allowances_to_0). That
migration was a one-time UPDATE, so it didn't cover rows inserted later by
upstream syncs -- notably migrations/versions/0547_new_sms_allowance_n_rate.py,
which added non-zero 2026 allowances. Re-applying the same blanket reset here
so those rows (and any future upstream ones) are zeroed again.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


restored_2026_allowances = {
    "central": 20_000,
    "nhs_central": 20_000,
    "local": 10_000,
    "nhs_local": 10_000,
    "emergency_service": 10_000,
    "school_or_college": 5_000,
    "other": 5_000,
    "nhs_gp": 0,
}


def upgrade():
    update_stmt = sa.update(
        sa.table(
            "default_annual_allowance",
            sa.column("allowance", sa.Integer)
        )
    ).values(allowance=0)

    op.execute(update_stmt)


def downgrade():
    table = sa.table(
        "default_annual_allowance",
        sa.column("organisation_type", sa.String),
        sa.column("allowance", sa.Integer),
        sa.column("valid_from_financial_year_start", sa.Integer),
    )

    for org_type, allowance in restored_2026_allowances.items():
        op.execute(
            sa.update(table)
            .where(
                table.c.valid_from_financial_year_start == 2026,
                table.c.organisation_type == org_type,
            )
            .values(allowance=allowance)
        )
