"""add template type messagebox

Revision ID: 0010
Revises: 0010
Create Date: 2025-11-21 15:05:59.982957

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


name = "template_type"
tmp_name = "tmp_" + name

old_options = ("sms", "email", "letter")
new_options = old_options + ("messagebox",)

new_type = sa.Enum(*new_options, name=name)
old_type = sa.Enum(*old_options, name=name)

tcr = sa.sql.table("templates", sa.Column("template_type", new_type, nullable=False))


def upgrade():
    op.execute("ALTER TYPE template_type ADD VALUE IF NOT EXISTS 'messagebox'")



def downgrade():
    # Convert 'letter' template into 'email'
    op.execute(tcr.update().where(tcr.c.template_type == "messagebox").values(template_type="email"))

    op.execute("ALTER TYPE " + name + " RENAME TO " + tmp_name)

    old_type.create(op.get_bind())
    op.execute(
        "ALTER TABLE templates ALTER COLUMN template_type " + "TYPE " + name + " USING template_type::text::" + name
    )
    op.execute("DROP TYPE " + tmp_name)
