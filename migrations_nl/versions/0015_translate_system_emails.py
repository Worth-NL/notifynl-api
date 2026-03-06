"""translate system emails

Revision ID: 0015
Revises: 0014
Create Date: 2026-03-06 12:15:32.735495

"""
from alembic import op
from sqlalchemy import text
from flask import current_app
from datetime import datetime, timezone

# revision identifiers, used by Alembic.
revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None

NOW = datetime.now(timezone.utc)

template_update = text("""
    UPDATE templates
    SET
        name = :name,
        content = :content,
        subject = :subject
    WHERE id = :id""")

template_history_update = text("""
    UPDATE templates_history
    SET
        name = :name,
        content = :content,
        subject = :subject
    WHERE id = :id""")

template_redacted_update = text("""
    UPDATE template_redacted
    SET
        redact_personalisation = :redact_personalisation,
        updated_at = :updated_at,
        updated_by_id = :updated_by_id
    WHERE template_id = :template_id""")


def upgrade():
    template_translations = [
        {
            "id": "afd325cd-c83e-4b0b-8426-7acb9c0aa62b",
            "name": "NotifyNL e-mail verificatiecode",
            "subject": "Bevestig je registratie bij NotifyNL",
            "content": """Hi ((name)),\n\n
                        Klik op de onderstaande link om je registratie bij NotifyNL te voltooien:\n\n((url))
                        """,
        },
        {
            "id": "b24bf0fa-dd64-4105-867c-4ed529e12df3",
            "name": "NotifyNL uitnodiging voor dienst per e-mail",
            "subject": "((user_name)) heeft je uitgenodigd om samen te werken op ((service_name)) via NotifyNL",
            "content": """((user_name)) heeft je uitgenodigd om samen te werken op ((service_name)) via NotifyNL.\n\n
                        NotifyNL maakt het eenvoudig om mensen op de hoogte te houden door je te helpen sms'jes en e-mails te versturen.\n\n
                        Klik op deze link om een account aan te maken bij NotifyNL:\n((url))\n\n
                        Deze uitnodiging vervalt morgen om middernacht. Dit is om ((service_name)) veilig te houden.
                        """,
        },
        {
            "id": "dfd254da-39d1-468f-bd0d-2c9e017c13a6",
            "name": "NotifyNL uitnodiging voor organisatie per e-mail",
            "subject": "((user_name)) heeft je uitgenodigd om samen te werken op ((organisation_name)) via NotifyNL",
            "content": """((user_name)) heeft je uitgenodigd om samen te werken op ((organisation_name)) via NotifyNL.\n\n
                        NotifyNL maakt het eenvoudig om mensen op de hoogte te houden door je te helpen sms'jes en e-mails te versturen.\n\n
                        Klik op deze link om een account aan te maken bij NotifyNL:\n((url))\n\n
                        Deze uitnodiging vervalt morgen om middernacht. Dit is om ((organisation_name)) veilig te houden.
                        """,
        },
        {
            "id": "f8209d70-9aa2-4a8c-89f9-00514492fa27",
            "name": "NotifyNL SMS verificatiecode",
            "subject": None,
            "content": "((verify_code)) is je NotifyNL verificatiecode",
        },
        {
            "id": "4cc48b09-62d0-473f-8514-3023b306a0fb",
            "name": "NotifyNL wachtwoord reset e-mail",
            "subject": "Reset je NotifyNL wachtwoord",
            "content": """Hi ((user_name)),\n\n
                        We hebben een verzoek ontvangen om je wachtwoord bij NotifyNL te resetten.\n\n
                        Als je dit verzoek niet hebt gedaan, kun je deze e-mail negeren – je wachtwoord is niet gewijzigd.\n\n
                        Om je wachtwoord te resetten, klik op deze link:\n\n
                        ((url))
                        """,
        },
        {
            "id": "bb3c17a8-6009-4f67-a943-353982c15c98",
            "name": "Je NotifyNL account",
            "subject": "Je NotifyNL account",
            "content": """Je hebt al een NotifyNL account met dit e-mailadres.\n\n
                        Log hier in: ((signin_url))\n\n
                        Als je je wachtwoord bent vergeten, kun je het hier resetten: ((forgot_password_url))\n\n
                        """,
        },
        {
            "id": "9eefb5bf-f1fb-46ce-9079-691260b0af9b",
            "name": "Bevestig nieuw e-mailadres",
            "subject": "Bevestig je nieuwe e-mailadres voor NotifyNL",
            "content": """Hi ((name)),\n\n
                        Klik op deze link om je nieuwe e-mailadres te bevestigen:\n\n((url))
                        """,
        },
        {
            "id": "320a5f19-600f-451e-9646-11206c69828d",
            "name": "NotifyNL e-mail verificatiecode",
            "subject": "Meld je aan bij NotifyNL",
            "content": """Hi ((name)),\n\n
                        Open deze link om je aan te melden bij NotifyNL: ((url))
                        """,
        },
        {
            "id": "fcf9095b-d1e3-46d9-b44f-752887c09322",
            "name": "Controleer reply-to e-mailadres voor een dienst op NotifyNL",
            "subject": "Je NotifyNL reply-to e-mailadres",
            "content": """Hi,\n\n
                        Dit adres is opgegeven als reply-to e-mailadres voor een NotifyNL account.\n
                        Alle antwoorden van gebruikers op e-mails die ze via NotifyNL ontvangen, worden naar dit adres gestuurd.\n\n
                        Dit is slechts een snelle controle om te bevestigen dat het adres geldig is.\n\n
                        Je hoeft hier niet op te reageren.
                        """,
        },
        {
            "id": "86761e21-b39c-43e1-a06b-a3340bc2bc7a",
            "name": "NotifyNL broadcast uitnodiging per e-mail",
            "subject": "((user_name)) heeft je uitgenodigd om deel te nemen aan ((service_name)) via NotifyNL",
            "content": """((user_name)) heeft je uitgenodigd om deel te nemen aan ((service_name)) via NotifyNL.\n\n
                        In een noodgeval kun je Notify gebruiken om een waarschuwing te sturen en het publiek te informeren over een direct levensgevaar.\n\n
                        Gebruik deze link om lid te worden van het team: ((url))\n\n
                        Deze uitnodiging vervalt morgen om middernacht. Dit is om ((service_name)) veilig te houden.
                        """,
        },
        {
            "id": "ec92ba79-222b-46f1-944a-79b3c072234d",
            "name": "Automatisch bericht \"Je bent nu actief\" op NotifyNL",
            "subject": "((service name)) is nu actief op NotifyNL",
            "content": """Hi ((name)),\n\n((service name)) is nu actief op NotifyNL.""",
        },
    ]

    for template in template_translations:
        op.execute(
            template_update.bindparams(
                name=template["name"],
                content=template["content"],
                subject=template["subject"],
                id=template["id"]
            )
        )

        op.execute(
            template_history_update.bindparams(
                name=template["name"],
                content=template["content"],
                subject=template["subject"],
                id=template["id"]
            )
        )

        op.execute(
            template_redacted_update.bindparams(
                redact_personalisation=False,
                updated_at=NOW,
                updated_by_id=current_app.config["NOTIFY_USER_ID"],
                template_id=template["id"]
            )
        )


def downgrade():
    old_templates = [
        {
            "id": "afd325cd-c83e-4b0b-8426-7acb9c0aa62b",
            "name": "NotifyNL email verification code",
            "subject": "Confirm NotifyNL registration",
            "content": """Hi ((name)),\n\n
                        To complete your registration for NotifyNL please click the link below\n\n((url))
                        """,
        },
        {
            "id": "b24bf0fa-dd64-4105-867c-4ed529e12df3",
            "name": "NotifyNL service invitation email",
            "subject": "((user_name)) has invited you to collaborate on ((service_name)) on NotifyNL",
            "content": """((user_name)) has invited you to collaborate on ((service_name)) on NotifyNL.\n\n
                        NotifyNL makes it easy to keep people updated by helping you send text messages and emails.\n\n
                        Click this link to create an account on NotifyNL:\n((url))\n\n
                        This invitation will stop working at midnight tomorrow. This is to keep ((service_name)) secure.
                        """,
        },
        {
            "id": "dfd254da-39d1-468f-bd0d-2c9e017c13a6",
            "name": "NotifyNL organisation invitation email",
            "subject": "((user_name)) has invited you to collaborate on ((organisation_name)) on NotifyNL",
            "content": """((user_name)) has invited you to collaborate on ((organisation_name)) on NotifyNL.\n\n
                        NotifyNL makes it easy to keep people updated by helping you send text messages and emails.\n\n
                        Click this link to create an account on NotifyNL:\n((url))\n\n
                        This invitation will stop working at midnight tomorrow. This is to keep ((organisation_name))
                        secure.
                        """,
        },
        {
            "id": "f8209d70-9aa2-4a8c-89f9-00514492fa27",
            "name": "NotifyNL SMS verify code",
            "subject": None,
            "content": "((verify_code)) is your NotifyNL authentication code",
        },
        {
            "id": "4cc48b09-62d0-473f-8514-3023b306a0fb",
            "name": "NotifyNL password reset email",
            "subject": "Reset your NotifyNL password",
            "content": """Hi ((user_name)),\n\n
                        We received a request to reset your password on NotifyNL.\n\n
                        If you didn''t request this email, you can ignore it –
                        your password has not been changed.\n\n
                        To reset your password, click this link:\n\n
                        ((url))
                        """,
        },
        {
            "id": "bb3c17a8-6009-4f67-a943-353982c15c98",
            "name": "Your NotifyNL account",
            "subject": "Your NotifyNL account",
            "content": """You already have a NotifyNL account with this email address.\n\n
                        Sign in here: ((signin_url))\n\n
                        If you''ve forgotten your password, you can reset it here: ((forgot_password_url))\n\n
                        """,
        },
        {
            "id": "9eefb5bf-f1fb-46ce-9079-691260b0af9b",
            "name": "Confirm new email address",
            "subject": "Confirm new email address for NotifyNL",
            "content": """Hi ((name)),\n\n
                            Click this link to confirm your new email address:\n\n((url))
                        """,
        },
        {
            "id": "320a5f19-600f-451e-9646-11206c69828d",
            "name": "NotifyNL email verify code",
            "subject": "Sign in to NotifyNL",
            "content": """Hi ((name)),\n\n
                            To sign in to NotifyNL please open this link: ((url))
                        """,
        },
        {
            "id": "fcf9095b-d1e3-46d9-b44f-752887c09322",
            "name": "Verify email reply-to address for a service on NotifyNL",
            "subject": "Your NotifyNL reply-to email address",
            "content": """Hi,\n\n
                        This address has been provided as a reply-to email address for a NotifyNL account.\n
                        Any replies from users to emails they receive through NotifyNL will come back to this email address.\n\n
                        This is just a quick check to make sure the address is valid.\n\n
                        No need to reply.
                        """,
        },
        {
            "id": "86761e21-b39c-43e1-a06b-a3340bc2bc7a",
            "name": "NotifyNL broadcast invitation email",
            "subject": "((user_name)) has invited you to join ((service_name)) on NotifyNL",
            "content": """((user_name)) has invited you to join ((service_name)) on NotifyNL.\n\n
                        In an emergency, use Notify to broadcast an alert, warning the public about an imminent risk
                        to life.\n\n
                        Use this link to join the team: ((url))\n\n
                        This invitation will stop working at midnight tomorrow. This is to keep ((service_name)) secure.
                        """,
        },
        {
            "id": "ec92ba79-222b-46f1-944a-79b3c072234d",
            "name": "Automated \"You''re now live\" message on NotifyNL",
            "subject": "((service name)) is now live on NotifyNL",
            "content": """Hi ((name)),\n\n((service name)) is now live on NotifyNL.""",
        },
    ]

    for template in old_templates:
        op.execute(
            template_update.bindparams(
                name=template["name"],
                content=template["content"],
                subject=template["subject"],
                id=template["id"]
            )
        )

        op.execute(
            template_history_update.bindparams(
                name=template["name"],
                content=template["content"],
                subject=template["subject"],
                id=template["id"]
            )
        )

        op.execute(
            template_redacted_update.bindparams(
                redact_personalisation=False,
                updated_at=NOW,
                updated_by_id=current_app.config["NOTIFY_USER_ID"],
                template_id=template["id"]
            )
        )