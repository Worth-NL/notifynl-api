"""Additional NotifyNL templates

Revision ID: 0002
Revises: 0001
Create Date: 2025-04-29 12:33:36.975727

"""
from alembic import op
from flask import current_app

# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


templates = [
    # Service is live
    # config.py/ConfigNL.SERVICE_NOW_LIVE_TEMPLATE_ID
    {
        "id": "ec92ba79-222b-46f1-944a-79b3c072234d",
        "name": "Automated \"You''re now live\" message on NotifyNL",
        "type": "email",
        "subject": "((service name)) is now live on NotifyNL",
        "content": """Hi ((name)),\n\n((service name)) is now live on NotifyNL.""",
    },
]


def upgrade():
    op.get_bind()
    insert = """INSERT INTO {} (id, name, template_type, created_at, content, archived, service_id,
                                subject, created_by_id, version, hidden, has_unsubscribe_link)
                VALUES ('{}', '{}', '{}', current_timestamp, '{}', False, '{}', '{}', '{}', 1, False, False)
            """

    template_redacted_insert = """INSERT INTO template_redacted (template_id, redact_personalisation,
                                                                updated_at, updated_by_id)
                                    VALUES ('{}', False, current_timestamp, '{}')
                                """

    for template in templates:
        for table_name in ["templates", "templates_history"]:
            op.execute(
                insert.format(
                    table_name,
                    template["id"],
                    template["name"],
                    template["type"],
                    template["content"],
                    current_app.config["NOTIFY_SERVICE_ID"],
                    template["subject"],
                    current_app.config["NOTIFY_USER_ID"]
                )
            )

        op.execute(
            template_redacted_insert.format(
                template["id"],
                current_app.config["NOTIFY_USER_ID"],
            )
        )


def downgrade():
    op.get_bind()

    for template in templates:
        op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template["id"]))
        op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(template["id"]))
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template["id"]))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template["id"]))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template["id"]))
