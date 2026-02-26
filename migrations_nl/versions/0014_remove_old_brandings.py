"""remove old brandings

Revision ID: 0014
Revises: 0013
Create Date: 2026-02-24 14:12:30.094965

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


OLD_EMAIL_BRANDINGS = [
	{
		"id" : "a7dc4e56-660b-4db7-8cff-12c37b12b5ea",
		"colour" : "",
		"logo" : "1ac6f483-3105-4c9e-9017-dd7fb2752c44-nhs-blue_x2.png",
		"name" : "NHS",
		"text" : "",
		"brand_type" : "org",
		"alt_text" : "NHS",
		"active" : True
	},
	{
		"id" : "9d25d02d-2915-4e98-874b-974e123e8536",
		"colour" : "#9325b2",
		"logo" : "ho_crest_27px_x2.png",
		"name" : "UK Visas & Immigration",
		"text" : "UK Visas & Immigration",
		"brand_type" : "org",
		"alt_text" : "",
		"active" : True
	},
	{
		"id" : "123496d4-44cb-4324-8e0a-4187101f4bdc",
		"colour" : "",
		"logo" : "data_gov_uk_x2.png",
		"name" : "data gov.uk",
		"text" : "data gov.uk",
		"brand_type" : "org",
		"alt_text" : "",
		"active" : True
	},
	{
		"id" : "1d70f564-919b-4c68-8bdf-b8520d92516e",
		"colour" : "",
		"logo" : "tfl_dar_x2.png",
		"name" : "tfl",
		"text" : "tfl",
		"brand_type" : "org",
		"alt_text" : "",
		"active" : True
	},
	{
		"id" : "89ce468b-fb29-4d5d-bd3f-d468fb6f7c36",
		"colour" : "",
		"logo" : "een_x2.png",
		"name" : "een",
		"text" : "een",
		"brand_type" : "org",
		"alt_text" : "",
		"active" : True
	}
]


OLD_LETTER_BRANDINGS = [
	{
		"id" : "dd494d9b-fdea-6d62-ede6-3303a1908371",
		"name" : "ACAS",
		"filename" : "acas"
	},
	{
		"id" : "8839e918-efb0-9c32-6cb1-a7d564c3bd68",
		"name" : "Anglesey Council",
		"filename" : "anglesey"
	},
	{
		"id" : "f6a254e7-7846-cdae-1aad-54c352659b59",
		"name" : "Angus Council",
		"filename" : "angus"
	},
	{
		"id" : "03960387-8151-d9a4-9711-664284f2659c",
		"name" : "Bournemouth Borough Council",
		"filename" : "bournemouth"
	},
	{
		"id" : "ebc0adb0-3f7f-17bf-ec6b-56cf4bb9b816",
		"name" : "Brighton and Hove city council",
		"filename" : "brighton-hove"
	},
	{
		"id" : "2b302da9-de1c-0120-848d-c45046421bcc",
		"name" : "Buckinghamshire County Council",
		"filename" : "buckinghamshire"
	},
	{
		"id" : "95f1ff4f-b645-0141-754b-b3c355d05e0e",
		"name" : "CADW",
		"filename" : "cadw"
	},
	{
		"id" : "0d65a338-c7ab-79c4-5ac5-dbfd02db58b4",
		"name" : "Cheshire East Council",
		"filename" : "cheshire-east"
	},
	{
		"id" : "496799ab-b554-a3e6-aea0-ad81115a6628",
		"name" : "Companies House",
		"filename" : "ch"
	},
	{
		"id" : "f39cf08a-7f26-90e3-cbfa-559d8c371207",
		"name" : "Department for Communities",
		"filename" : "dept-for-communities"
	},
	{
		"id" : "de41f642-8ef3-d185-e545-77e62b67e98d",
		"name" : "Department for Work and Pensions",
		"filename" : "dwp"
	},
	{
		"id" : "a58ad7be-8b45-18a2-f23f-13baa6d815a1",
		"name" : "Disclosure and Barring Service",
		"filename" : "dbs"
	},
	{
		"id" : "f629c3de-f564-087f-6c15-2e6710415dae",
		"name" : "DWP (Welsh)",
		"filename" : "dwp-welsh"
	},
	{
		"id" : "22072af1-984f-a395-ab4a-305efc8cbad1",
		"name" : "East Riding of Yorkshire Council",
		"filename" : "eryc"
	},
	{
		"id" : "051ef214-c86d-1659-9b79-8d2efb60e5b9",
		"name" : "Environment Agency (PDF letters ONLY)",
		"filename" : "ea"
	},
	{
		"id" : "627b6219-0c2f-8d81-1cdc-eb04a53c90a4",
		"name" : "Government Equalities Office",
		"filename" : "geo"
	},
	{
		"id" : "d73b2a1b-183f-5427-9c65-b407f2fed16e",
		"name" : "Hackney Council",
		"filename" : "hackney"
	},
	{
		"id" : "fd1a219c-da9b-ecce-82e5-c8ab14aca4d0",
		"name" : "Hampshire County Council",
		"filename" : "hants"
	},
	{
		"id" : "d36c3522-ae10-c0bb-3b8b-350650b181e6",
		"name" : "HM Government",
		"filename" : "hm-government"
	},
	{
		"id" : "c3e9bda1-4f4d-6853-8431-6bb93fe4c4fc",
		"name" : "HM Passport Office",
		"filename" : "hmpo"
	},
	{
		"id" : "ed2c1b6d-4896-af07-5d66-96b2ec981152",
		"name" : "Land Registry",
		"filename" : "hm-land-registry"
	},
	{
		"id" : "35794daa-ae84-fe99-dc31-7a69b9fa58c3",
		"name" : "Marine Management Organisation",
		"filename" : "mmo"
	},
	{
		"id" : "b56a5b87-638d-18f5-abf7-e0df3721111d",
		"name" : "Natural Resources Wales",
		"filename" : "natural-resources-wales"
	},
	{
		"id" : "799fff36-6eca-7640-fba6-0f889a8c1bc5",
		"name" : "Neath Port Talbot Council",
		"filename" : "npt"
	},
	{
		"id" : "be2a1373-da8c-50db-3187-04a036baed82",
		"name" : "Newham Council",
		"filename" : "newham"
	},
	{
		"id" : "2cd354bb-6b85-eda3-c0ad-6b613150459f",
		"name" : "NHS",
		"filename" : "nhs"
	},
	{
		"id" : "3b26bc2d-45cc-cc57-fb60-12fff39cf1fb",
		"name" : "North Somerset Council",
		"filename" : "north-somerset"
	},
	{
		"id" : "de46cfe7-b060-83c8-0477-a3968b4c246b",
		"name" : "North Yorkshire Council",
		"filename" : "north-yorkshire"
	},
	{
		"id" : "f0737770-e395-807d-c2be-71f31ea0dfeb",
		"name" : "Office of the Public Guardian",
		"filename" : "opg"
	},
	{
		"id" : "0f131b70-941a-aa75-7146-06eb4eaa13df",
		"name" : "Ofgem",
		"filename" : "ofgem"
	},
	{
		"id" : "7fc1a834-5713-89a2-f3bf-0ba662a649fb",
		"name" : "Pension Wise",
		"filename" : "pension-wise"
	},
	{
		"id" : "ced92475-d5f1-cb08-bb95-61d3f3049941",
		"name" : "Redbridge Council",
		"filename" : "redbridge"
	},
	{
		"id" : "da4e3071-7c1a-1ebd-e2b1-e926eaf97c73",
		"name" : "Rother and Wealden",
		"filename" : "wdc"
	},
	{
		"id" : "6e2ecf27-474a-6ddb-55f7-76938a7a04e8",
		"name" : "Rother District Council",
		"filename" : "rother"
	},
	{
		"id" : "fc52514f-c8e3-5af3-5fb3-926134e9f481",
		"name" : "Thames Valley Police",
		"filename" : "thames-valley-police"
	},
	{
		"id" : "5bd0aaa4-771d-0dbb-4a1d-a1649a0a68ac",
		"name" : "Tyne and Wear Fire and Rescue Service",
		"filename" : "twfrs"
	},
	{
		"id" : "e1368a91-f1c7-27db-a1d1-ede4e18de74b",
		"name" : "Vale of Glamorgan",
		"filename" : "vale-of-glamorgan"
	},
	{
		"id" : "9179502d-f339-63aa-d3c9-7817e5a7fe2f",
		"name" : "Warwickshire Council",
		"filename" : "warwickshire"
	},
	{
		"id" : "443388c5-f832-f388-fd26-74a0e3794e49",
		"name" : "Welsh Revenue Authority",
		"filename" : "wra"
	},
	{
		"id" : "b6a7632b-00fe-423f-3e41-058d86824d87",
		"name" : "Wigan Council",
		"filename" : "wigan"
	},
	{
		"id" : "731e5396-1288-0542-838e-cf72beb55544",
		"name" : "Worcestershire County Council",
		"filename" : "worcestershire"
	}
]


def upgrade():
    for i in OLD_EMAIL_BRANDINGS:
      branding_id = i["id"]

      op.execute(
        sa.text(
          f"DELETE FROM email_branding WHERE id = '{branding_id}';"
        )
      )

    for i in OLD_LETTER_BRANDINGS:
      branding_id = i["id"]

      op.execute(
        sa.text(
          f"DELETE FROM letter_branding WHERE id = '{branding_id}';"
        )
      )


def downgrade():
    for i in OLD_EMAIL_BRANDINGS:
      branding_id = i["id"]
      colour = i["colour"]
      logo = i["logo"]
      name = i["name"]
      text = i["text"]
      brand_type = i["brand_type"]
      alt_text = i["alt_text"]
      active = i["active"]

      op.execute(
        sa.text(
          f"""INSERT INTO email_branding (id, colour, logo, name, text, brand_type, alt_text, active)
          VALUES ('{branding_id}', '{colour}', '{logo}', '{name}', '{text}', '{brand_type}', '{alt_text}', {'TRUE' if active else 'FALSE'})
          """
        )
      )

    for i in OLD_LETTER_BRANDINGS:
      branding_id = i["id"]
      name = i["name"]
      filename = i["filename"]

      op.execute(
        sa.text(
          f"""INSERT INTO letter_branding (id, name, filename)
          VALUES ('{branding_id}', '{name}', '{filename}')
          """
        )
      )
