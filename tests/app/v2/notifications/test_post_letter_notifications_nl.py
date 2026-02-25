import pytest

from app.config import QueueNames
from app.constants import (
    LETTER_TYPE,
    NOTIFICATION_CREATED,
)
from app.models import Job, Notification
from app.schema_validation import validate
from app.v2.notifications.notification_schemas import post_letter_response
from tests.app.db import create_service, create_template


@pytest.mark.parametrize("reference", [None, "reference_from_client"])
def test_post_letter_notification_returns_201(api_client_request, sample_letter_template, mocker, reference):
    mock = mocker.patch("app.celery.letters_pdf_tasks.get_pdf_for_templated_letter.apply_async")
    data = {
        "template_id": str(sample_letter_template.id),
        "personalisation": {
            "address_line_1": "Recipient",
            "address_line_2": "StreetName",
            "postcode": "1234 AB City",
            "name": "Lizzie",
        },
    }

    if reference:
        data.update({"reference": reference})

    resp_json = api_client_request.post(
        sample_letter_template.service_id, "v2_notifications.post_notification", notification_type="letter", _data=data
    )

    assert validate(resp_json, post_letter_response) == resp_json
    assert Job.query.count() == 0
    notification = Notification.query.one()
    assert notification.status == NOTIFICATION_CREATED
    assert resp_json["id"] == str(notification.id)
    assert resp_json["reference"] == reference
    assert resp_json["content"]["subject"] == sample_letter_template.subject
    assert resp_json["content"]["body"] == sample_letter_template.content
    assert f"v2/notifications/{notification.id}" in resp_json["uri"]
    assert resp_json["template"]["id"] == str(sample_letter_template.id)
    assert resp_json["template"]["version"] == sample_letter_template.version
    assert (
        f"services/{sample_letter_template.service_id}/templates/{sample_letter_template.id}"
        in resp_json["template"]["uri"]
    )
    assert not resp_json["scheduled_for"]
    assert not notification.reply_to_text
    mock.assert_called_once_with([str(notification.id)], queue=QueueNames.CREATE_LETTERS_PDF)


def test_post_letter_notification_sets_postage(api_client_request, notify_db_session, mocker):
    service = create_service(service_permissions=[LETTER_TYPE])
    template = create_template(service, template_type="letter", postage="netherlands")
    mocker.patch("app.celery.letters_pdf_tasks.get_pdf_for_templated_letter.apply_async")
    data = {
        "template_id": str(template.id),
        "personalisation": {
            "address_line_1": "Recipient",
            "address_line_2": "StreetName",
            "postcode": "1234 AB City",
            "name": "Lizzie",
        },
    }

    resp_json = api_client_request.post(
        service.id, "v2_notifications.post_notification", notification_type="letter", _data=data
    )

    assert validate(resp_json, post_letter_response) == resp_json
    notification = Notification.query.one()
    assert notification.postage == "netherlands"


def test_post_letter_notification_formats_postcode(api_client_request, notify_db_session, mocker):
    service = create_service(service_permissions=[LETTER_TYPE])
    template = create_template(service, template_type="letter")
    mocker.patch("app.celery.letters_pdf_tasks.get_pdf_for_templated_letter.apply_async")
    data = {
        "template_id": str(template.id),
        "personalisation": {
            "address_line_1": "Recipient",
            "address_line_2": "StreetName",
            "postcode": "1234 ab   City",
            "name": "Lizzie",
        },
    }

    resp_json = api_client_request.post(
        service.id, "v2_notifications.post_notification", notification_type="letter", _data=data
    )

    assert validate(resp_json, post_letter_response) == resp_json
    notification = Notification.query.one()
    # We store what the client gives us, and only reformat it when
    # generating the PDF
    assert notification.personalisation["postcode"] == "1234 ab   City"
