"""translate remaining system emails

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-20 00:00:00.000000

"""
from datetime import datetime, timezone

from alembic import op
from flask import current_app
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '0025'
down_revision = '0024'
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
            "id": "c73f1d71-4049-46d5-a647-d013bdeca3f0",
            "name": "E-mailadres gewijzigd door dienstbeheerder",
            "subject": "Je NotifyNL e-mailadres is gewijzigd",
            "content": """Beste ((name)),\n\n"""
            """((servicemanagername)) heeft het e-mailadres van je NotifyNL-account gewijzigd naar:\n\n"""
            """((email address))\n\n"""
            """Je moet dit e-mailadres gebruiken de volgende keer dat je inlogt.\n\n"""
            """Met vriendelijke groet\n\n"""
            """Het NotifyNL team\n"""
            """https://admin.notifynl.nl""",
        },
        {
            "id": "8a31520f-4751-4789-8ea1-fe54496725eb",
            "name": "Telefoonnummer gewijzigd door dienstbeheerder",
            "subject": None,
            "content": (
                "Je mobiele nummer is gewijzigd door ((servicemanagername)). "
                "De volgende keer dat je inlogt, wordt je NotifyNL-verificatiecode naar dit nummer gestuurd."
            ),
        },
        {
            "id": "4fd2e43c-309b-4e50-8fb8-1955852d9d71",
            "name": "MOU Signed By Receipt",
            "subject": "Je hebt de NotifyNL-verwerkersovereenkomst en financiële overeenkomst geaccepteerd",
            "content": """Beste ((signed_by_name)),\n\n"""
            """((org_name)) heeft de NotifyNL-verwerkersovereenkomst en financiële overeenkomst geaccepteerd.\n\n"""
            """Als je een nieuwe kopie van de overeenkomst nodig hebt, kun je die hier downloaden: ((mou_link))\n\n"""
            """Met vriendelijke groet,\n"""
            """Het NotifyNL team\n\n"""
            """https://admin.notifynl.nl""",
        },
        {
            "id": "c20206d5-bf03-4002-9a90-37d5032d9e84",
            "name": "MOU Signed On Behalf Of Receipt - Signed by",
            "subject": "Je hebt de NotifyNL-verwerkersovereenkomst en financiële overeenkomst geaccepteerd",
            "content": """Beste ((signed_by_name)),\n\n"""
            """((org_name)) heeft de NotifyNL-verwerkersovereenkomst en financiële overeenkomst geaccepteerd. """
            """We hebben ((on_behalf_of_name)) hierover ook per e-mail geïnformeerd.\n\n"""
            """Als je een nieuwe kopie van de overeenkomst nodig hebt, kun je die hier downloaden: ((mou_link))\n\n"""
            """Met vriendelijke groet,\n"""
            """Het NotifyNL team\n\n"""
            """https://admin.notifynl.nl""",
        },
        {
            "id": "522b6657-5ca5-4368-a294-6b527703bd0b",
            "name": "MOU Signed On Behalf Of Receipt - On Behalf Of",
            "subject": "((org_name)) heeft de NotifyNL-verwerkersovereenkomst en financiële overeenkomst geaccepteerd",
            "content": """Beste ((on_behalf_of_name)),\n\n"""
            """((signed_by_name)) heeft namens ((org_name)) de NotifyNL-verwerkersovereenkomst """
            """en financiële overeenkomst geaccepteerd.\n\n"""
            """NotifyNL maakt het voor teams binnen de (semi-)publieke sector mogelijk om e-mails, """
            """sms-berichten en brieven te versturen. Bevat overheidsinformatie die is gelicentieerd onder """
            """de Open Government Licence v3.0. Wijzigingen en aanvullende inhoud voor de NL-fork zijn """
            """gelicentieerd onder de European Union Public Licence (EUPL), tenzij anders vermeld.\n\n"""
            """Als je een nieuwe kopie van de overeenkomst nodig hebt, kun je die hier downloaden: ((mou_link))\n\n"""
            """Met vriendelijke groet,\n"""
            """Het NotifyNL team\n\n"""
            """https://admin.notifynl.nl""",
        },
        {
            "id": "5c7cfc0f-c3f4-4bd6-9a84-5a144aad5425",
            "name": "Dienst wil live gaan (voor organisatiegebruikers)",
            "subject": "Verzoek om live te gaan: ((service_name))",
            "content": """Hoi ((name))\n\n"""
            """((requester_name)) heeft verzocht om '((service_name))' live te laten gaan.\n\n"""
            """# Dit verzoek goed- of afkeuren\n\n"""
            """Bekijk dit verzoek op: ((make_service_live_link))\n\n"""
            """# Vragen?\n\n"""
            """Om ((requester_name)) iets over hun dienst te vragen, kun je op deze e-mail reageren """
            """of rechtstreeks contact opnemen via ((requester_email_address))\n\n"""
            """***\n\n"""
            """Je ontvangt deze e-mail omdat je teamlid bent van ((organisation_name)) op NotifyNL.\n\n"""
            """Als je hulp nodig hebt met dit verzoek of iets anders, neem dan contact op via """
            """onze supportpagina: ((support_page_link))\n\n"""
            """Met vriendelijke groet,\n"""
            """Het NotifyNL team\n\n"""
            """https://admin.notifynl.nl""",
        },
        {
            "id": "507d0796-9e23-4ad7-b83b-5efbd9496866",
            "name": "Verzoek om live te gaan via zelfbediening afgewezen",
            "subject": "Je verzoek om live te gaan is afgewezen",
            "content": """Hoi ((name))\n\n"""
            """# Je verzoek om live te gaan is afgewezen\n\n"""
            """Je hebt een verzoek gestuurd om de NotifyNL-dienst '((service_name))' live te laten gaan.\n\n"""
            """((organisation_team_member_name)) van ((organisation_name)) heeft het verzoek afgewezen """
            """om de volgende reden:\n\n"""
            """((reason))\n\n"""
            """Als je vragen hebt, kun je een e-mail sturen naar ((organisation_team_member_name)) """
            """via ((organisation_team_member_email))\n\n"""
            """Met vriendelijke groet\n\n"""
            """Het NotifyNL team\n"""
            """https://admin.notifynl.nl""",
        },
        {
            "id": "77677459-f862-44ee-96d9-b8cb2323d407",
            "name": "Verzoek om uitgenodigd te worden voor een dienst",
            "subject": "((requester_name)) wil zich aansluiten bij jouw NotifyNL-dienst",
            "content": """Hoi ((approver_name))\n\n"""
            """((requester_name)) heeft gevraagd om zich aan te sluiten bij de volgende NotifyNL-dienst:\n\n"""
            """^((service_name))\n\n"""
            """((reason_given??Ze gaven de volgende reden om zich te willen aansluiten:))\n\n"""
            """((reason))\n\n"""
            """# Wat je moet doen\n\n"""
            """Gebruik deze link om het verzoek goed te keuren of te weigeren:\n\n"""
            """((url))\n\n"""
            """## Vragen?\n\n"""
            """Je kunt een e-mail sturen naar ((requester_name)) via ((requester_email_address))\n\n"""
            """Met vriendelijke groet\n\n"""
            """Het NotifyNL team\n"""
            """https://admin.notifynl.nl""",
        },
        {
            "id": "38bcd263-6ce8-431f-979d-8e637c1f0576",
            "name": "Je hebt gevraagd om aan te sluiten bij een NotifyNL-dienst",
            "subject": "Je hebt gevraagd om aan te sluiten bij een NotifyNL-dienst",
            "content": """Hoi ((requester_name))\n\n"""
            """Je hebt gevraagd om je aan te sluiten bij de volgende NotifyNL-dienst:\n\n"""
            """^((service_name))\n\n"""
            """Als je een update wilt over je verzoek, kun je contact opnemen met:\n\n"""
            """((service_admin_names))\n\n"""
            """Reageren ze niet? Dan kun je [een ander teamlid vragen je verzoek goed te keuren]"""
            """(((url_ask_to_join_page))).\n\n"""
            """Met vriendelijke groet\n\n"""
            """Het NotifyNL team\n"""
            """https://admin.notifynl.nl""",
        },
        {
            "id": "4d8ee728-100e-4f0e-8793-5638cfa4ffa4",
            "name": "03 - Aanvrager - Je verzoek is goedgekeurd",
            "subject": "((approver_name)) heeft je verzoek goedgekeurd",
            "content": """Hoi ((requester_name))\n\n"""
            """((approver_name)) heeft je verzoek om je aan te sluiten bij de volgende NotifyNL-dienst """
            """goedgekeurd:\n\n"""
            """^[((service_name))](((dashboard_url)))\n\n"""
            """Log in bij NotifyNL om aan de slag te gaan.\n\n"""
            """Met vriendelijke groet\n\n"""
            """Het NotifyNL team\n"""
            """https://admin.notifynl.nl""",
        },
        {
            "id": "c7083bfe-1b9a-4ff9-bd5c-30508727df6e",
            "name": "Ontvangstbevestiging na verzoek om live te gaan (zelfgoedkeuring)",
            "subject": "Je verzoek om live te gaan",
            "content": """Hoi ((name))\n\n"""
            """Je hebt een verzoek gestuurd om de NotifyNL-dienst '((service_name))' live te laten gaan.\n\n"""
            """Je verzoek is verstuurd naar de volgende teamleden van ((organisation_name)):\n\n"""
            """((organisation_team_member_names))\n\n"""
            """Als je binnen 2 werkdagen geen update over je verzoek ontvangt, reageer dan op deze e-mail """
            """om het ons te laten weten.\n\n"""
            """Met vriendelijke groet\n\n"""
            """Het NotifyNL team\n"""
            """https://admin.notifynl.nl""",
        },
        {
            "id": "55bcb671-4924-46c5-a00d-1a9d48458008",
            "name": "Enquête voor nieuwe gebruikers",
            "subject": "Hoe makkelijk was het om te starten met NotifyNL?",
            "content": """Hoi ((name))\n"""
            """# Hoe makkelijk was het om te starten met NotifyNL?\n\n"""
            """We horen graag hoe je ervaring was. Neem gerust contact met ons op via onze supportpagina: """
            """https://admin.notifynl.nl/support\n\n"""
            """Vertel ons over je ervaringen tot nu toe – van het aanmaken van een account tot het """
            """instellen van je eerste dienst.\n\n"""
            """We lezen alle feedback die we ontvangen, en jouw inzichten helpen ons om NotifyNL """
            """voor iedereen beter te maken.\n\n"""
            """Met vriendelijke groet\n"""
            """Het NotifyNL team\n\n"""
            """---\n\n"""
            """Wil je niet deelnemen aan gebruikersonderzoek? Dan kun je je afmelden via """
            """https://admin.notifynl.nl/your-account/take-part-in-user-research.""",
        },
        {
            "id": "ec92ba79-222b-46f1-944a-79b3c072234d",
            "name": 'Geautomatiseerd "Je bent nu live"-bericht',
            "subject": "((service name)) is nu live op NotifyNL",
            "content": """Beste ((name)),\n\n"""
            """De volgende NotifyNL-dienst is nu live:\n\n"""
            """^((service name))\n\n"""
            """Deze e-mail bevat belangrijke informatie over:\n\n"""
            """* dingen die je nu moet doen\n"""
            """* wat je moet doen als je een probleem hebt\n\n"""
            """---\n\n"""
            """#Dingen die je nu moet doen\n\n"""
            """##Als je sms-berichten of brieven verstuurt\n\n"""
            """Je moet ons een inkooporder sturen voordat je geld uitgeeft aan sms-berichten of brieven.\n\n"""
            """[Lees hoe je een inkooporder kunt aanmaken](https://docs.notifynl.nl/pricing)\n\n"""
            """##Als je e-mails verstuurt\n\n"""
            """Controleer of je afmeldlinks moet toevoegen aan je e-mailsjablonen.\n\n"""
            """[Bekijk onze richtlijnen voor meer informatie]"""
            """(https://docs.notifynl.nl/using-notify/unsubscribe-links)\n\n"""
            """##Als je onze API gebruikt\n\n"""
            """Je kunt nu berichten versturen naar iedereen door een live API-sleutel aan te maken.\n\n"""
            """[Bekijk onze API-documentatie voor instructies](https://docs.notifynl.nl)\n\n"""
            """---\n\n"""
            """#Als je een probleem hebt\n\n"""
            """##Voordat je contact opneemt met het team\n\n"""
            """Abonneer je op onze statuspagina om e-mailupdates te ontvangen:\n"""
            """https://status.notifynl.nl\n\n"""
            """Als de statuspagina een probleem toont, werken we al aan een oplossing — """
            """je hoeft dan geen contact met ons op te nemen.\n\n"""
            """##Hoe je contact opneemt met het team\n\n"""
            """[Gebruik de supportpagina om een probleem te melden of een vraag te stellen]"""
            """(https://admin.notifynl.nl/support).\n\n"""
            """Bij een noodgeval reageren we binnen 30 minuten.\n\n"""
            """Voor alle andere zaken reageren we uiterlijk aan het einde van de volgende werkdag.\n\n"""
            """Onze werkdagen zijn maandag tot en met vrijdag, van 9:30 tot 17:30, """
            """met uitzondering van feestdagen.\n\n"""
            """##Wat geldt als een noodgeval?\n\n"""
            """Het is alleen een noodgeval als je:\n\n"""
            """* een foutmelding 'technical difficulties' krijgt bij het versturen van een bericht\n"""
            """* een 500-responscode ontvangt bij het versturen van berichten via de API\n\n"""
            """##Als je buiten kantooruren een noodgeval hebt\n\n"""
            """Gebruik alsnog de [supportpagina](https://admin.notifynl.nl/support).\n\n"""
            """Als je de supportpagina niet kunt gebruiken, stuur dan een e-mail naar:\n"""
            """info@worth.nl\n\n"""
            """Gebruik dit e-mailadres uitsluitend voor noodgevallen buiten kantooruren.\n\n"""
            """Deel dit e-mailadres niet met mensen buiten je team.\n\n"""
            """---\n\n"""
            """Bedankt\n\n"""
            """NotifyNL\n"""
            """https://www.notificatie.nl""",
        },
    ]

    for template in template_translations:
        op.execute(
            template_update.bindparams(
                name=template["name"],
                content=template["content"],
                subject=template["subject"],
                id=template["id"],
            )
        )

        op.execute(
            template_history_update.bindparams(
                name=template["name"],
                content=template["content"],
                subject=template["subject"],
                id=template["id"],
            )
        )

        op.execute(
            template_redacted_update.bindparams(
                redact_personalisation=False,
                updated_at=NOW,
                updated_by_id=current_app.config["NOTIFY_USER_ID"],
                template_id=template["id"],
            )
        )


def downgrade():
    old_templates = [
        {
            "id": "c73f1d71-4049-46d5-a647-d013bdeca3f0",
            "name": "Email address changed by service manager",
            "subject": "Your GOV.UK Notify email address has changed",
            "content": """Dear ((name)),\n\n"""
            """((servicemanagername)) changed your Notify account email address to:\n\n"""
            """((email address))\n\n"""
            """You’ll need to use this email address next time you sign in.\n\n"""
            """Thanks\n\n"""
            """GOV.​UK Notify team\n"""
            """https://www.gov.uk/notify""",
        },
        {
            "id": "8a31520f-4751-4789-8ea1-fe54496725eb",
            "name": "Phone number changed by service manager",
            "subject": None,
            "content": (
                "Your mobile number was changed by ((servicemanagername)). Next time you sign in, "
                "your Notify authentication code will be sent to this phone."
            ),
        },
        {
            "id": "4fd2e43c-309b-4e50-8fb8-1955852d9d71",
            "name": "MOU Signed By Receipt",
            "subject": "You’ve accepted the GOV.​UK Notify data sharing and financial agreement",
            "content": """Hi ((signed_by_name)),\n\n"""
            """((org_name)) has accepted the GOV.​UK Notify data sharing and financial agreement. \n\n"""
            """If you need another copy of the agreement you can download it here: ((mou_link))\n\n"""
            """Thanks,\n"""
            """GOV.​UK Notify team\n\n"""
            """https://www.gov.uk/notify""",
        },
        {
            "id": "c20206d5-bf03-4002-9a90-37d5032d9e84",
            "name": "MOU Signed On Behalf Of Receipt - Signed by",
            "subject": "You’ve accepted the GOV.​UK Notify data sharing and financial agreement",
            "content": """Hi ((signed_by_name)),\n\n"""
            """((org_name)) has accepted the GOV.​UK Notify data sharing and financial agreement. """
            """We’ve emailed ((on_behalf_of_name)) to let them know too.\n\n"""
            """If you need another copy of the agreement you can download it here: ((mou_link))\n\n"""
            """Thanks,\n"""
            """GOV.​UK Notify team\n\n"""
            """https://www.gov.uk/notify""",
        },
        {
            "id": "522b6657-5ca5-4368-a294-6b527703bd0b",
            "name": "MOU Signed On Behalf Of Receipt - On Behalf Of",
            "subject": "((org_name)) has accepted the GOV.​UK Notify data sharing and financial agreement",
            "content": """Hi ((on_behalf_of_name)),\n\n"""
            """((signed_by_name)) has accepted the GOV.​UK Notify data sharing and financial agreement """
            """on your behalf, for ((org_name)).\n\n"""
            """GOV.​UK Notify lets teams in the public sector send emails, text messages and letters. """
            """It’s built and run by a team in the Government Digital Service (part of Cabinet Office).\n\n"""
            """If you need another copy of the agreement you can download it here: ((mou_link))\n\n"""
            """Thanks,\n"""
            """GOV.​UK Notify team\n\n"""
            """https://www.gov.uk/notify""",
        },
        {
            "id": "5c7cfc0f-c3f4-4bd6-9a84-5a144aad5425",
            "name": "Service wants to go live (for organisation users)",
            "subject": "Request to go live: ((service_name))",
            "content": """Hi ((name))\n\n"""
            """((requester_name)) has requested for '((service_name))' to be made live.\n\n"""
            """# To approve or reject this request\n\n"""
            """Review this request at: ((make_service_live_link))\n\n"""
            """# If you have any questions\n\n"""
            """To ask ((requester_name)) about their service reply to this email or contact them directly """
            """at ((requester_email_address))\n\n"""
            """***\n\n"""
            """You are receiving this email because you are a team member of ((organisation_name)) """
            """on GOV.UK Notify.\n\n"""
            """If you need help with this request or anything else, get in touch via our support page """
            """at ((support_page_link))\n\n"""
            """Thanks,\n"""
            """GOV.​UK Notify team\n\n"""
            """https://www.gov.uk/notify""",
        },
        {
            "id": "507d0796-9e23-4ad7-b83b-5efbd9496866",
            "name": "Reject self-service go live request",
            "subject": "Your request to go live has been rejected",
            "content": """Hi ((name))\n\n"""
            """# Your request to go live was rejected\n\n"""
            """You sent a request to go live for a GOV.UK Notify service called '((service_name))'.\n\n"""
            """((organisation_team_member_name)) at ((organisation_name)) rejected the request for the """
            """following reason:\n\n"""
            """((reason))\n\n"""
            """If you have any questions, you can email ((organisation_team_member_name)) at """
            """((organisation_team_member_email))\n\n"""
            """Thanks\n\n"""
            """GOV.​UK Notify team\n"""
            """https://www.gov.uk/notify""",
        },
        {
            "id": "77677459-f862-44ee-96d9-b8cb2323d407",
            "name": "Request invite to a service",
            "subject": "((requester_name)) wants to join your GOV.UK Notify service",
            "content": """Hi ((approver_name))\n\n"""
            """((requester_name)) has asked to join the following GOV.UK Notify service:\n\n"""
            """^((service_name))\n\n"""
            """((reason_given??They gave the following reason for wanting to join:))\n\n"""
            """((reason))\n\n"""
            """# What you need to do\n\n"""
            """Use this link to approve or refuse their request:\n\n"""
            """((url))\n\n"""
            """## If you have any questions\n\n"""
            """You can email ((requester_name)) at ((requester_email_address))\n\n"""
            """Thanks\n\n"""
            """GOV.​UK Notify\n"""
            """https://www.gov.uk/notify""",
        },
        {
            "id": "38bcd263-6ce8-431f-979d-8e637c1f0576",
            "name": "You have asked to join a GOV.UK Notify service",
            "subject": "You have asked to join a GOV.UK Notify service",
            "content": """Hi ((requester_name))\n\n"""
            """You have asked to join the following GOV.UK Notify service:\n\n"""
            """^((service_name))\n\n"""
            """If you need an update about your request, you can contact:\n\n"""
            """((service_admin_names))\n\n"""
            """If they do not reply, you can [ask a different team member to approve your request]"""
            """(((url_ask_to_join_page))).\n\n"""
            """Thanks\n\n"""
            """GOV.​UK Notify\n"""
            """https://www.gov.uk/notify""",
        },
        {
            "id": "4d8ee728-100e-4f0e-8793-5638cfa4ffa4",
            "name": "03 - Requester - Your request has been approved",
            "subject": "((approver_name)) has approved your request",
            "content": """Hi ((requester_name))\n\n"""
            """((approver_name)) has approved your request to join the following GOV.UK Notify service:\n\n"""
            """^[((service_name))](((dashboard_url)))\n\n"""
            """Sign in to GOV.UK Notify to get started.\n\n"""
            """Thanks\n\n"""
            """GOV.​UK Notify\n"""
            """https://www.gov.uk/notify""",
        },
        {
            "id": "c7083bfe-1b9a-4ff9-bd5c-30508727df6e",
            "name": "Receipt email after requesting to go live (self-approval)",
            "subject": "Your request to go live",
            "content": """Hi ((name))\n\n"""
            """You have sent a request to go live for a GOV.​UK Notify service called """
            """'((service_name))'.\n\n"""
            """Your request was sent to the following members of ((organisation_name)):\n\n"""
            """((organisation_team_member_names)) \n\n"""
            """If you do not receive an update about your request in the next 2 working days, please """
            """reply to this email and let us know.\n\n"""
            """Thanks\n\n"""
            """GOV.​UK Notify team\n"""
            """https://www.gov.uk/notify""",
        },
        {
            "id": "55bcb671-4924-46c5-a00d-1a9d48458008",
            "name": "New user survey",
            "subject": "How easy was it to start using GOV.UK Notify?",
            "content": """Hi ((name))\n"""
            """# How easy was it to start using GOV.UK Notify?\n\n"""
            """Please take 30 seconds to let us know:\n\n"""
            """https://surveys.publishing.service.gov.uk/s/notify-getting-started/\n\n"""
            """If you want to, you can tell us more about your experiences so far – from creating an """
            """account to setting up your first service.\n\n"""
            """We’ll read every piece of feedback we get, and your insights will help us to make """
            """GOV.UK Notify better for everyone.\n\n"""
            """Kind regards\n"""
            """GOV.UK Notify\n\n"""
            """---\n\n"""
            """If you do not want to take part in user research, you can [unsubscribe from these emails]"""
            """(https://www.notifications.service.gov.uk/your-account/take-part-in-user-research).""",
        },
        {
            "id": "ec92ba79-222b-46f1-944a-79b3c072234d",
            "name": 'Automatisch bericht "Je bent nu actief" op NotifyNL',
            "subject": "((service name)) is nu actief op NotifyNL",
            "content": """Hi ((name)),\n\n((service name)) is nu actief op NotifyNL.""",
        },
    ]

    for template in old_templates:
        op.execute(
            template_update.bindparams(
                name=template["name"],
                content=template["content"],
                subject=template["subject"],
                id=template["id"],
            )
        )

        op.execute(
            template_history_update.bindparams(
                name=template["name"],
                content=template["content"],
                subject=template["subject"],
                id=template["id"],
            )
        )

        op.execute(
            template_redacted_update.bindparams(
                redact_personalisation=False,
                updated_at=NOW,
                updated_by_id=current_app.config["NOTIFY_USER_ID"],
                template_id=template["id"],
            )
        )
