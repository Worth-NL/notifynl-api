"""change default annual allowance

Revision ID: 0007
Revises: 0006
Create Date: 2025-06-20 10:47:28.618784

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""UPDATE default_annual_allowance
               SET allowance = 0
               """)


def downgrade():
    default_allowances = [
        {
            "id": "e88573e7-0208-41a0-8151-4de0fac7efcd",
            "valid_from_financial_year_start": 2016,
            "organisation_type": "central",
            "allowance": 250000,
            "notification_type": "sms"
        },
        {
            "id": "47266278-eb11-43a3-b6d0-320d4cfcaf17",
            "valid_from_financial_year_start": 2021,
            "organisation_type": "central",
            "allowance": 150000,
            "notification_type": "sms"
        },
        {
            "id": "6ed51647-ffc0-4115-adec-a6593334adbb",
            "valid_from_financial_year_start": 2022,
            "organisation_type": "central",
            "allowance": 40000,
            "notification_type": "sms"
        },
        {
            "id": "450825e2-927a-4413-9bf6-19a42ed66a37",
            "valid_from_financial_year_start": 2023,
            "organisation_type": "central",
            "allowance": 40000,
            "notification_type": "sms"
        },
        {
            "id": "916f882c-815c-436b-9cbe-db8569ce0cbc",
            "valid_from_financial_year_start": 2016,
            "organisation_type": "local",
            "allowance": 25000,
            "notification_type": "sms"
        },
        {
            "id": "96986306-b679-4a70-8fd5-0385e2f4e38c",
            "valid_from_financial_year_start": 2021,
            "organisation_type": "local",
            "allowance": 25000,
            "notification_type": "sms"
        },
        {
            "id": "a1cf2d1f-a473-4fff-b801-0571938449cf",
            "valid_from_financial_year_start": 2022,
            "organisation_type": "local",
            "allowance": 20000,
            "notification_type": "sms"
        },
        {
            "id": "4c30519a-48a6-49ad-884b-a30c0b1d0cf9",
            "valid_from_financial_year_start": 2023,
            "organisation_type": "local",
            "allowance": 20000,
            "notification_type": "sms"
        },
        {
            "id": "8469a139-f6d8-452d-a171-a2decb5b0664",
            "valid_from_financial_year_start": 2016,
            "organisation_type": "nhs_central",
            "allowance": 250000,
            "notification_type": "sms"
        },
        {
            "id": "f2a0bfa4-ac09-4c32-adee-6410427e0872",
            "valid_from_financial_year_start": 2021,
            "organisation_type": "nhs_central",
            "allowance": 150000,
            "notification_type": "sms"
        },
        {
            "id": "595e1ae1-b78e-4922-8c3a-ed9100a0356e",
            "valid_from_financial_year_start": 2022,
            "organisation_type": "nhs_central",
            "allowance": 40000,
            "notification_type": "sms"
        },
        {
            "id": "3a9efa73-7bf6-48e4-b1a1-9baaaef6b902",
            "valid_from_financial_year_start": 2023,
            "organisation_type": "nhs_central",
            "allowance": 40000,
            "notification_type": "sms"
        },
        {
            "id": "baf655a4-6b7a-47d1-ba92-83f83ee4f3ce",
            "valid_from_financial_year_start": 2016,
            "organisation_type": "nhs_local",
            "allowance": 25000,
            "notification_type": "sms"
        },
        {
            "id": "5b78c0de-0d77-44d8-bde3-3604bdc7707e",
            "valid_from_financial_year_start": 2021,
            "organisation_type": "nhs_local",
            "allowance": 25000,
            "notification_type": "sms"
        },
        {
            "id": "32e9d36d-6e60-4387-922d-c5747d26e2d3",
            "valid_from_financial_year_start": 2022,
            "organisation_type": "nhs_local",
            "allowance": 20000,
            "notification_type": "sms"
        },
        {
            "id": "e169662f-8c2c-4374-b5d1-92e336f7cc5a",
            "valid_from_financial_year_start": 2023,
            "organisation_type": "nhs_local",
            "allowance": 20000,
            "notification_type": "sms"
        },
        {
            "id": "57a87067-ea42-4e69-9f28-01a4e7f6da5d",
            "valid_from_financial_year_start": 2016,
            "organisation_type": "nhs_gp",
            "allowance": 25000,
            "notification_type": "sms"
        },
        {
            "id": "a04dfd08-54d7-438a-b437-e3d089b07ed2",
            "valid_from_financial_year_start": 2021,
            "organisation_type": "nhs_gp",
            "allowance": 10000,
            "notification_type": "sms"
        },
        {
            "id": "245f1c44-a669-486a-9938-6d3281cd556b",
            "valid_from_financial_year_start": 2022,
            "organisation_type": "nhs_gp",
            "allowance": 10000,
            "notification_type": "sms"
        },
        {
            "id": "aff5e21e-f68a-4864-804c-2ece82adfdde",
            "valid_from_financial_year_start": 2023,
            "organisation_type": "nhs_gp",
            "allowance": 10000,
            "notification_type": "sms"
        },
        {
            "id": "18b4c13c-c38a-4057-b055-fa00f53283f9",
            "valid_from_financial_year_start": 2016,
            "organisation_type": "emergency_service",
            "allowance": 25000,
            "notification_type": "sms"
        },
        {
            "id": "2ccf09ce-fb8e-4bbe-afd7-c156718b63ed",
            "valid_from_financial_year_start": 2021,
            "organisation_type": "emergency_service",
            "allowance": 25000,
            "notification_type": "sms"
        },
        {
            "id": "68514c78-219a-4feb-9993-932a90565ab9",
            "valid_from_financial_year_start": 2022,
            "organisation_type": "emergency_service",
            "allowance": 20000,
            "notification_type": "sms"
        },
        {
            "id": "e3938653-4ec8-4928-b7c1-2c614a01ee28",
            "valid_from_financial_year_start": 2023,
            "organisation_type": "emergency_service",
            "allowance": 20000,
            "notification_type": "sms"
        },
        {
            "id": "30ffb21e-f28a-4477-b6cf-09ec9151cdfc",
            "valid_from_financial_year_start": 2016,
            "organisation_type": "school_or_college",
            "allowance": 25000,
            "notification_type": "sms"
        },
        {
            "id": "194ea847-320e-4663-b06a-bbd63f831aca",
            "valid_from_financial_year_start": 2021,
            "organisation_type": "school_or_college",
            "allowance": 10000,
            "notification_type": "sms"
        },
        {
            "id": "a310c613-2a7c-42d3-8a95-85e82173b4ee",
            "valid_from_financial_year_start": 2022,
            "organisation_type": "school_or_college",
            "allowance": 10000,
            "notification_type": "sms"
        },
        {
            "id": "7595f477-18b2-4b75-ab0e-f884ee3a2fe2",
            "valid_from_financial_year_start": 2023,
            "organisation_type": "school_or_college",
            "allowance": 10000,
            "notification_type": "sms"
        },
        {
            "id": "bee907d7-a39f-474a-a28a-1c454a3a24e1",
            "valid_from_financial_year_start": 2016,
            "organisation_type": "other",
            "allowance": 25000,
            "notification_type": "sms"
        },
        {
            "id": "98374569-dc8b-469c-be5e-071c634a00a1",
            "valid_from_financial_year_start": 2021,
            "organisation_type": "other",
            "allowance": 10000,
            "notification_type": "sms"
        },
        {
            "id": "bf6fdc17-d033-4724-bfc5-598470bb2ff8",
            "valid_from_financial_year_start": 2022,
            "organisation_type": "other",
            "allowance": 10000,
            "notification_type": "sms"
        },
        {
            "id": "65ac216b-7e45-4862-b6fd-35465b39d22e",
            "valid_from_financial_year_start": 2023,
            "organisation_type": "other",
            "allowance": 10000,
            "notification_type": "sms"
        },
        {
            "id": "425a0a7c-0114-40c0-a605-1fde5d11a807",
            "valid_from_financial_year_start": 2024,
            "organisation_type": "central",
            "allowance": 30000,
            "notification_type": "sms"
        },
        {
            "id": "4e0019ff-f899-4e13-9e7c-bb38d6029744",
            "valid_from_financial_year_start": 2024,
            "organisation_type": "nhs_central",
            "allowance": 30000,
            "notification_type": "sms"
        },
        {
            "id": "802ef432-ad1b-46e5-8331-a4985a004ab3",
            "valid_from_financial_year_start": 2024,
            "organisation_type": "local",
            "allowance": 10000,
            "notification_type": "sms"
        },
        {
            "id": "a69cb110-2103-46bd-80a8-57e70bea7b45",
            "valid_from_financial_year_start": 2024,
            "organisation_type": "nhs_local",
            "allowance": 10000,
            "notification_type": "sms"
        },
        {
            "id": "12718b87-24e2-466c-a5ab-b3513e98661e",
            "valid_from_financial_year_start": 2024,
            "organisation_type": "emergency_service",
            "allowance": 10000,
            "notification_type": "sms"
        },
        {
            "id": "06c6eddd-fc7a-4afc-a485-778b7a59e38f",
            "valid_from_financial_year_start": 2024,
            "organisation_type": "school_or_college",
            "allowance": 5000,
            "notification_type": "sms"
        },
        {
            "id": "dbdeb45f-18f9-43b7-b848-3ae59ef7e8d9",
            "valid_from_financial_year_start": 2024,
            "organisation_type": "other",
            "allowance": 5000,
            "notification_type": "sms"
        },
        {
            "id": "03e8af73-cb49-4895-ac9e-e99bd8d786df",
            "valid_from_financial_year_start": 2024,
            "organisation_type": "nhs_gp",
            "allowance": 0,
            "notification_type": "sms"
        }
    ]

    for record in default_allowances:
        op.execute(f"""UPDATE default_annual_allowance
                   SET allowance = {record["allowance"]}
                   WHERE id = {record["id"]}
                   """)
