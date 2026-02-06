"""set free allowances to 0

Revision ID: 0007
Revises: 0006
Create Date: 2025-12-15 16:04:24.729091

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


allowances = {
    "e88573e7-0208-41a0-8151-4de0fac7efcd": 250000,
    "47266278-eb11-43a3-b6d0-320d4cfcaf17": 150000,
    "6ed51647-ffc0-4115-adec-a6593334adbb": 40000,
    "450825e2-927a-4413-9bf6-19a42ed66a37": 40000,
    "916f882c-815c-436b-9cbe-db8569ce0cbc": 25000,
    "96986306-b679-4a70-8fd5-0385e2f4e38c": 25000,
    "a1cf2d1f-a473-4fff-b801-0571938449cf": 20000,
    "4c30519a-48a6-49ad-884b-a30c0b1d0cf9": 20000,
    "8469a139-f6d8-452d-a171-a2decb5b0664": 250000,
    "f2a0bfa4-ac09-4c32-adee-6410427e0872": 150000,
    "595e1ae1-b78e-4922-8c3a-ed9100a0356e": 40000,
    "3a9efa73-7bf6-48e4-b1a1-9baaaef6b902": 40000,
    "baf655a4-6b7a-47d1-ba92-83f83ee4f3ce": 25000,
    "5b78c0de-0d77-44d8-bde3-3604bdc7707e": 25000,
    "32e9d36d-6e60-4387-922d-c5747d26e2d3": 20000,
    "e169662f-8c2c-4374-b5d1-92e336f7cc5a": 20000,
    "57a87067-ea42-4e69-9f28-01a4e7f6da5d": 25000,
    "a04dfd08-54d7-438a-b437-e3d089b07ed2": 10000,
    "245f1c44-a669-486a-9938-6d3281cd556b": 10000,
    "aff5e21e-f68a-4864-804c-2ece82adfdde": 10000,
    "18b4c13c-c38a-4057-b055-fa00f53283f9": 25000,
    "2ccf09ce-fb8e-4bbe-afd7-c156718b63ed": 25000,
    "68514c78-219a-4feb-9993-932a90565ab9": 20000,
    "e3938653-4ec8-4928-b7c1-2c614a01ee28": 20000,
    "30ffb21e-f28a-4477-b6cf-09ec9151cdfc": 25000,
    "194ea847-320e-4663-b06a-bbd63f831aca": 10000,
    "a310c613-2a7c-42d3-8a95-85e82173b4ee": 10000,
    "7595f477-18b2-4b75-ab0e-f884ee3a2fe2": 10000,
    "bee907d7-a39f-474a-a28a-1c454a3a24e1": 25000,
    "98374569-dc8b-469c-be5e-071c634a00a1": 10000,
    "bf6fdc17-d033-4724-bfc5-598470bb2ff8": 10000,
    "65ac216b-7e45-4862-b6fd-35465b39d22e": 10000,
    "d8c8598a-bb5b-4963-a3d7-caa5d2b9d2b1": 30000,
    "acc9d2dd-cdd1-4382-b74f-12ce0164ac7e": 30000,
    "70615e52-c90f-4dc9-a64b-9ed81ecdaf31": 10000,
    "9fac8e6d-9974-495b-aac5-860e17105170": 10000,
    "29f25c47-067f-469c-8ea9-844db30368d9": 10000,
    "e189398b-7e04-4cca-94cf-026e3546d39f": 5000,
    "dab23316-65c7-46ff-a829-bab2b5862c8f": 5000,
    "f36afa17-472a-4e4b-9f4a-f35790c1e4df": 0
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
        sa.column("id", sa.Integer),
        sa.column("allowance", sa.Integer),
    )

    for k, v in allowances.items():
        op.execute(
            sa.update(table)
            .where(table.c.id == k)
            .values(allowance=v)
        )
