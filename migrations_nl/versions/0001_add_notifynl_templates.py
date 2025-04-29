"""Add NotifyNL templates

Revision ID: 0001
Revises: None
Create Date: 2025-04-29 12:15:32.597184

"""
from alembic import op
from flask import current_app

# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


templates = [
    # Create new account
    {
        "id": "afd325cd-c83e-4b0b-8426-7acb9c0aa62b",
        "name": "NotifyNL email verification code",
        "type": "email",
        "subject": "Confirm NotifyNL registration",
        "content": """Hi ((name)),\n\n
                    To complete your registration for NotifyNL please click the link below\n\n((url))
                    """,
    },
    # Invitation to collaborate - service
    {
        "id": "b24bf0fa-dd64-4105-867c-4ed529e12df3",
        "name": "NotifyNL service invitation email",
        "type": "email",
        "subject": "((user_name)) has invited you to collaborate on ((service_name)) on NotifyNL",
        "content": """((user_name)) has invited you to collaborate on ((service_name)) on NotifyNL.\n\n
                    NotifyNL makes it easy to keep people updated by helping you send text messages and emails.\n\n
                    Click this link to create an account on NotifyNL:\n((url))\n\n
                    This invitation will stop working at midnight tomorrow. This is to keep ((service_name)) secure.
                    """,
    },
    # Invitation to collaborate - organisation
    {
        "id": "dfd254da-39d1-468f-bd0d-2c9e017c13a6",
        "name": "NotifyNL organisation invitation email",
        "type": "email",
        "subject": "((user_name)) has invited you to collaborate on ((organisation_name)) on NotifyNL",
        "content": """((user_name)) has invited you to collaborate on ((organisation_name)) on NotifyNL.\n\n
                    NotifyNL makes it easy to keep people updated by helping you send text messages and emails.\n\n
                    Click this link to create an account on NotifyNL:\n((url))\n\n
                    This invitation will stop working at midnight tomorrow. This is to keep ((organisation_name))
                    secure.
                    """,
    },
    # SMS verification code
    {
        "id": "f8209d70-9aa2-4a8c-89f9-00514492fa27",
        "name": "NotifyNL SMS verify code",
        "type": "sms",
        "subject": None,
        "content": "((verify_code)) is your NotifyNL authentication code",
    },
    # Password reset
    {
        "id": "4cc48b09-62d0-473f-8514-3023b306a0fb",
        "name": "NotifyNL password reset email",
        "type": "email",
        "subject": "Reset your NotifyNL password",
        "content": """Hi ((user_name)),\n\n
                    We received a request to reset your password on NotifyNL.\n\n
                    If you didn''t request this email, you can ignore it –
                    your password has not been changed.\n\n
                    To reset your password, click this link:\n\n
                    ((url))
                    """,
    },
    # Create account for existing email
    {
        "id": "bb3c17a8-6009-4f67-a943-353982c15c98",
        "name": "Your NotifyNL account",
        "type": "email",
        "subject": "Your NotifyNL account",
        "content": """You already have a NotifyNL account with this email address.\n\n
                    Sign in here: ((signin_url))\n\n
                    If you''ve forgotten your password, you can reset it here: ((forgot_password_url))\n\n
                    """,
    },
    # Change email address
    {
        "id": "9eefb5bf-f1fb-46ce-9079-691260b0af9b",
        "name": "Confirm new email address",
        "type": "email",
        "subject": "Confirm new email address for NotifyNL",
        "content": """Hi ((name)),\n\n
                        Click this link to confirm your new email address:\n\n((url))
                    """,
    },
    # Email verification code
    {
        "id": "320a5f19-600f-451e-9646-11206c69828d",
        "name": "NotifyNL email verify code",
        "type": "email",
        "subject": "Sign in to NotifyNL",
        "content": """Hi ((name)),\n\n
                        To sign in to NotifyNL please open this link: ((url))
                    """,
    },
    # Verify reply-to address
    {
        "id": "fcf9095b-d1e3-46d9-b44f-752887c09322",
        "name": "Verify email reply-to address for a service on NotifyNL",
        "type": "email",
        "subject": "Your NotifyNL reply-to email address",
        "content": """Hi,\n\n
                    This address has been provided as a reply-to email address for a NotifyNL account.\n
                    Any replies from users to emails they receive through NotifyNL will come back to this email
                    address.\n\n
                    This is just a quick check to make sure the address is valid.\n\n
                    No need to reply.
                    """,
    },
    # Broadcast invitation email
    {
        "id": "86761e21-b39c-43e1-a06b-a3340bc2bc7a",
        "name": "NotifyNL broadcast invitation email",
        "type": "email",
        "subject": "((user_name)) has invited you to join ((service_name)) on NotifyNL",
        "content": """((user_name)) has invited you to join ((service_name)) on NotifyNL.\n\n
                    In an emergency, use Notify to broadcast an alert, warning the public about an imminent risk
                    to life.\n\n
                    Use this link to join the team: ((url))\n\n
                    This invitation will stop working at midnight tomorrow. This is to keep ((service_name)) secure.
                    """,
    },
]


def upgrade():
    op.get_bind()
    insert = """INSERT INTO {} (id, name, template_type, created_at, content, archived, service_id,
                                subject, created_by_id, version, process_type, hidden, has_unsubscribe_link)
                VALUES ('{}', '{}', '{}', current_timestamp, '{}', False, '{}', '{}', '{}', 1, 'normal', False, False)
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
