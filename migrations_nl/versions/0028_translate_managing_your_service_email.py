"""translate 'Managing your service' email sent when a service goes live

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-01 00:00:00.000000

"""
from datetime import datetime, timezone

from alembic import op
from flask import current_app
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None

NOW = datetime.now(timezone.utc)

# Added in English by upstream migration 0561 (MANAGING_YOUR_SERVICE_TEMPLATE_ID)
TEMPLATE_ID = "999813a9-d7d2-4b61-bc68-73b59937ca4e"

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

NL_NAME = "Je NotifyNL-dienst beheren"
NL_SUBJECT = "Belangrijk: je NotifyNL-dienst beheren"
NL_CONTENT = """Beste ((name)),

Deze e-mail bevat belangrijke informatie over NotifyNL:

* bewaar deze e-mail op een plek waar je hem terugvindt
* deel deze e-mail niet buiten je team

#Je NotifyNL-dienst beheren

Je ontvangt deze e-mail omdat je de toestemming ‘Instellingen, team en gebruik beheren’ hebt voor de volgende dienst:

^((service name))

---

#1. Zorg voor je team

Zorg ervoor dat er altijd minstens 2 actieve teamleden zijn met de toestemming ‘Instellingen, team en gebruik beheren’.

##Als de inloggegevens van een teamlid zijn gewijzigd

Het is jouw verantwoordelijkheid om hun e-mailadres of telefoonnummer bij te werken.

Zij hoeven hiervoor geen contact op te nemen met support.

---

#2. Als je sms-berichten of brieven verstuurt

Je bent ervoor verantwoordelijk dat je organisatie ons een inkooporder stuurt.

[Lees hoe je een inkooporder kunt aanmaken](https://docs.notifynl.nl/pricing)

---

#3. Hoe je NotifyNL-support gebruikt

##Abonneer je op onze statuspagina

Je hoeft geen contact met ons op te nemen als je probleem al op de [statuspagina](https://status.notifynl.nl) staat.

##Als je vastloopt

Lees onze [documentatie](https://docs.notifynl.nl).

##Een probleem melden

[Gebruik de supportpagina om een probleem te melden](https://admin.notifynl.nl/support)

We beoordelen je melding en reageren:

* binnen 30 minuten als het om een noodgeval gaat
* uiterlijk aan het einde van de volgende werkdag voor alle andere zaken

Onze werkdagen zijn maandag tot en met vrijdag, van 9:30 tot 17:30, met uitzondering van feestdagen.

##Als de supportpagina niet werkt

Neem alleen contact met ons op als je een van de volgende foutmeldingen ziet:

* een foutmelding ‘technical difficulties’ bij het versturen van een bericht
* een 500-responscode bij het versturen van berichten via de API

Als je een van deze foutmeldingen ziet en de supportpagina niet kunt gebruiken, stuur dan een e-mail naar: info@worth.nl

Gebruik dit e-mailadres niet voor andere problemen of vragen.

Deel dit e-mailadres nooit met mensen buiten je team.

---

Met vriendelijke groet

NotifyNL
https://www.notificatie.nl
"""

# Upstream 0561's original English name and subject; downgrade restores these with 0561's own content.
EN_NAME = "Managing your GOV.UK Notify service"
EN_SUBJECT = "Important: Managing your GOV.UK Notify service"


def _update(name, subject, content):
    op.execute(template_update.bindparams(name=name, content=content, subject=subject, id=TEMPLATE_ID))
    op.execute(template_history_update.bindparams(name=name, content=content, subject=subject, id=TEMPLATE_ID))
    op.execute(
        template_redacted_update.bindparams(
            redact_personalisation=False,
            updated_at=NOW,
            updated_by_id=current_app.config["NOTIFY_USER_ID"],
            template_id=TEMPLATE_ID,
        )
    )


def upgrade():
    _update(NL_NAME, NL_SUBJECT, NL_CONTENT)


def downgrade():
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).parents[2] / "migrations" / "versions" / "0561_add_go_live_admin_template.py"
    spec = importlib.util.spec_from_file_location("upstream_0561", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _update(EN_NAME, EN_SUBJECT, module.template_content)
