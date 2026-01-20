"""Go-live template translation

Revision ID: 0008
Revises: 0007
Create Date: 2026-01-20 09:43:13.159280

"""
from alembic import op
from sqlalchemy import text
from flask import current_app
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

TEMPLATE_ID = "618185c6-3636-49cd-b7d2-6f6f5eb3bdde"
NOW = datetime.now(timezone.utc)


template_update = text("""
    UPDATE templates
    SET
        name = :name,
        template_type = :template_type,
        created_at = :created_at,
        content = :content,
        archived = FALSE,
        service_id = :service_id,
        subject = :subject,
        created_by_id = :created_by_id,
        version = 1
    WHERE id = :id""")
template_history_update = text("""
    UPDATE templates_history
    SET
        name = :name,
        template_type = :template_type,
        created_at = :created_at,
        content = :content,
        archived = FALSE,
        service_id = :service_id,
        subject = :subject,
        created_by_id = :created_by_id,
        version = 1
    WHERE id = :id""")
template_redacted_update = text("""
    UPDATE template_redacted
    SET
        redact_personalisation = :redact_personalisation,
        updated_at = :updated_at,
        updated_by_id = :updated_by_id
    WHERE template_id = :template_id""")


def upgrade():
    template_name = "Geautomatiseerd \"Je bent nu live\"-bericht"
    template_subject = "((service name)) is nu live op NotifyNL"
    template_content = """Beste ((name)),

De volgende NotifyNL-dienst is nu live:

^((service name))

Deze e-mail bevat belangrijke informatie over:

* dingen die je nu moet doen
* wat je moet doen als je een probleem hebt

---

#Dingen die je nu moet doen

##Als je sms-berichten of brieven verstuurt

Je moet ons een inkooporder sturen voordat je geld uitgeeft aan sms-berichten of brieven.

[Lees hoe je een inkooporder kunt aanmaken](https://docs.notifynl.nl/pricing)

##Als je e-mails verstuurt

Controleer of je afmeldlinks moet toevoegen aan je e-mailsjablonen.

[Bekijk onze richtlijnen voor meer informatie](https://docs.notifynl.nl/using-notify/unsubscribe-links)

##Als je onze API gebruikt

Je kunt nu berichten versturen naar iedereen door een live API-sleutel aan te maken.

[Bekijk onze API-documentatie voor instructies](https://docs.notifynl.nl)

---

#Als je een probleem hebt

##Voordat je contact opneemt met het team

Abonneer je op onze statuspagina om e-mailupdates te ontvangen:
https://status.notifynl.nl

Als de statuspagina een probleem toont, werken we al aan een oplossing — je hoeft dan geen contact met ons op te nemen.

##Hoe je contact opneemt met het team

[Gebruik de supportpagina om een probleem te melden of een vraag te stellen](https://admin.notifynl.nl/support).

Bij een noodgeval reageren we binnen 30 minuten.

Voor alle andere zaken reageren we uiterlijk aan het einde van de volgende werkdag.

Onze werkdagen zijn maandag tot en met vrijdag, van 9:30 tot 17:30, met uitzondering van feestdagen.

##Wat geldt als een noodgeval?

Het is alleen een noodgeval als je:

* een foutmelding ‘technical difficulties’ krijgt bij het versturen van een bericht
* een 500-responscode ontvangt bij het versturen van berichten via de API

##Als je buiten kantooruren een noodgeval hebt

Gebruik alsnog de [supportpagina](https://admin.notifynl.nl/support).

Als je de supportpagina niet kunt gebruiken, stuur dan een e-mail naar:
ooh-gov-uk-notify-support@digital.cabinet-office.gov.uk

Gebruik dit e-mailadres uitsluitend voor noodgevallen buiten kantooruren.

Deel dit e-mailadres niet met mensen buiten je team.

---

Bedankt

NotifyNL
https://www.notificatie.nl
"""

    op.execute(
        template_update.bindparams(
            name=template_name,
            template_type="email",
            created_at=NOW,
            content=template_content,
            service_id=current_app.config["NOTIFY_SERVICE_ID"],
            subject=template_subject,
            created_by_id=current_app.config["NOTIFY_USER_ID"],
            id=TEMPLATE_ID
        )
    )

    op.execute(
        template_history_update.bindparams(
            name=template_name,
            template_type="email",
            created_at=NOW,
            content=template_content,
            service_id=current_app.config["NOTIFY_SERVICE_ID"],
            subject=template_subject,
            created_by_id=current_app.config["NOTIFY_USER_ID"],
            id=TEMPLATE_ID
        )
    )

    op.execute(
        template_redacted_update.bindparams(
            template_id=TEMPLATE_ID,
            redact_personalisation=False,
            updated_at=NOW,
            updated_by_id=current_app.config['NOTIFY_USER_ID']
        )
    )


def downgrade():
    old_template_name = "Automated \"You''re now live\" message"
    old_template_subject = "((service name)) is now live on GOV.UK Notify"
    old_template_content = """Dear ((name)),

The following GOV.​UK Notify service is now live:

^((service name))

This email includes important information about:

* things you need to do now
* what to do if you have a problem


---

#Things you need to do now

##If you send text messages or letters

You must send us a purchase order before you spend any money on text messages or letters.

[Find out how to raise a purchase order](https://www.notifications.service.gov.uk/pricing/how-to-pay)

##If you send emails

Check if you need to add unsubscribe links to your email templates.

[See our guidance for more information](https://www.notifications.service.gov.uk/using-notify/unsubscribe-links)

##If you use our API

You can now send messages to anyone by creating a live API key.

[See our API documentation for instructions](https://www.notifications.service.gov.uk/documentation)

---

#If you have a problem

##Before you contact the team

Subscribe to our status page to get email updates: https://status.notifications.service.gov.uk

If the status page shows a problem, we’re already working on a solution – you do not need to contact us.

##How to contact the team

[Use the support page to report a problem or ask a question](https://www.notifications.service.gov.uk/support).

If it’s an emergency we’ll reply within 30 minutes.

For everything else, we’ll reply by the end of the next working day.

Our working days are Monday to Friday, 9:30am to 5:30pm, excluding bank holidays.

##What counts as an emergency?

It’s only an emergency if you get:

* a ‘technical difficulties’ error when you try to send a message
* a 500 response code when you try to send messages using the API

##If you have an out-of-hours emergency

You should still [use the support page](https://www.notifications.service.gov.uk/support).

If you cannot use the support page, email:
ooh-gov-uk-notify-support@digital.cabinet-office.gov.uk

You must only use this email address for out-of-hours emergencies.

Do not share this email address with people outside your team.

---

Thanks

GOV.​UK Notify
https://www.gov.uk/notify
"""

    op.execute(
        template_update.bindparams(
            name=old_template_name,
            template_type="email",
            created_at=NOW,
            content=old_template_content,
            service_id=current_app.config["NOTIFY_SERVICE_ID"],
            subject=old_template_subject,
            created_by_id=current_app.config["NOTIFY_USER_ID"],
            id=TEMPLATE_ID
        )
    )

    op.execute(
        template_history_update.bindparams(
            name=old_template_name,
            template_type="email",
            created_at=NOW,
            content=old_template_content,
            service_id=current_app.config["NOTIFY_SERVICE_ID"],
            subject=old_template_subject,
            created_by_id=current_app.config["NOTIFY_USER_ID"],
            id=TEMPLATE_ID
        )
    )
