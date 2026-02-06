from flask import current_app

from app.constants import MESSAGEBOX_TYPE
from app.dao.templates_dao import dao_create_template
from app.dao.users_dao import get_user_by_id
from app.models import Template


def get_messagebox_template(service_id):
    template = Template.query.filter_by(service_id=service_id, template_type=MESSAGEBOX_TYPE, hidden=True).first()
    if template is not None:
        return template

    template = Template(
        name="Berichtenbox bericht",
        created_by=get_user_by_id(current_app.config["NOTIFY_USER_ID"]),
        service_id=service_id,
        template_type=MESSAGEBOX_TYPE,
        hidden=True,
        subject="Berichtenbox bericht",
        content="Notify heeft geen toegang tot de inhoud van berichtenbox berichten.",
        postage="",
    )

    dao_create_template(template)

    return template
