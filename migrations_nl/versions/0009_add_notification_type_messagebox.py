"""add notification type messagebox

Revision ID: 0009
Revises: 0009
Create Date: 2025-11-21 15:05:59.982957

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0009'
down_revision = '0007'
branch_labels = None
depends_on = None

name = "notification_type"
tmp_name = "tmp_" + name

old_options = ("sms", "email","letter")
new_options = old_options + ("messagebox",)

old_type = sa.Enum(*old_options, name=name)
new_type  = sa.Enum(*new_options, name=name)

tcr = sa.sql.table("notifications", sa.Column("notification_type", new_type, nullable=False))

def upgrade():
    # Add new value to enum
    drop_dependant_view()
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'messagebox'")
    recreate_view()

def downgrade():
    drop_dependant_view()
    # Downgrading a PostgreSQL ENUM is tricky — cannot remove values directly.
    # Only way is to recreate the enum:

    # Convert 'letter' template into 'email'
    op.execute(tcr.update().where(tcr.c.template_type == "messagebox").values(template_type="email"))

    op.execute("ALTER TYPE " + name + " RENAME TO " + tmp_name)
    old_type.create(op.get_bind())

    op.execute("ALTER TABLE notifications ALTER COLUMN notification_type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notificationtype_tmp")

    recreate_view()


def drop_dependant_view():
  op.execute("drop view IF EXISTS notifications_all_time_view")

def recreate_view():
    op.execute(
        """
        CREATE OR REPLACE VIEW notifications_all_time_view AS
        (
            SELECT
                id,
                job_id,
                job_row_number,
                service_id,
                template_id,
                template_version,
                api_key_id,
                key_type,
                billable_units,
                notification_type,
                created_at,
                sent_at,
                sent_by,
                updated_at,
                notification_status,
                reference,
                client_reference,
                international,
                phone_prefix,
                rate_multiplier,
                created_by_id,
                postage,
                document_download_count
            FROM notifications
        ) UNION ALL
        (
            SELECT
                id,
                job_id,
                job_row_number,
                service_id,
                template_id,
                template_version,
                api_key_id,
                key_type,
                billable_units,
                notification_type,
                created_at,
                sent_at,
                sent_by,
                updated_at,
                notification_status,
                reference,
                client_reference,
                international,
                phone_prefix,
                rate_multiplier,
                created_by_id,
                postage,
                document_download_count
            FROM notification_history
        )
    """
    )
