"""translate DVLA letter volume email

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-20 00:00:00.000000

"""
from datetime import datetime, timezone

from alembic import op
from flask import current_app
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None

NOW = datetime.now(timezone.utc)

TEMPLATE_ID = "11fad854-fd38-4a7c-bd17-805fb13dfc12"

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
    name = "Dagelijkse brievenvolumes NotifyNL"
    subject = "NotifyNL brievenvolume voor ((date)): ((total_volume)) brieven, ((total_sheets)) vellen"
    content = "\n".join(
        [
            "((total_volume)) brieven (((total_sheets)) vellen) verzonden via NotifyNL komen aan in de "
            "batch van vandaag. Dit omvat: ",
            "",
            "((netherlands_volume)) brieven binnen Nederland (((netherlands_sheets)) vellen).",
            "((europe_volume)) brieven naar Europa (((europe_sheets)) vellen).",
            "((rest_of_world_volume)) brieven naar de rest van de wereld (((rest_of_world_sheets)) vellen).",
            "",
            "Met vriendelijke groet",
            "",
            "Het NotifyNL team",
            "https://admin.notifynl.nl",
        ]
    )

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


def downgrade():
    name = "Notify daily letter volumes"
    subject = "Notify letter volume for ((date)): ((total_volume)) letters, ((total_sheets)) sheets"
    content = "\n".join(
        [
            "((total_volume)) letters (((total_sheets)) sheets) sent via Notify are coming in today's "
            "batch. These include: ",
            "",
            "((first_class_volume)) first class letters (((first_class_sheets)) sheets).",
            "((second_class_volume)) second class letters (((second_class_sheets)) sheets).",
            "((economy_mail_volume)) economy mail letters (((economy_mail_sheets)) sheets).",
            "((international_volume)) international letters (((international_sheets)) sheets).",
            "",
            "Thanks",
            "",
            "GOV.​UK Notify team",
            "https://www.gov.uk/notify",
        ]
    )

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
