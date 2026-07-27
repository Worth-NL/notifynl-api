from unittest.mock import ANY

import pytest

from app.config import QueueNames, TaskNamesNL
from app.constants import (
    LETTER_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_PENDING_VIRUS_CHECK,
)
from app.models import Job, Notification
from app.notifications.process_letter_notifications import create_letter_notification
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
    mock.assert_called_once_with(
        [str(notification.id)],
        queue=QueueNames.CREATE_LETTERS_PDF,
        MessageGroupId=str(sample_letter_template.service_id),
    )


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


def test_post_precompiled_letter_notification_with_contents_returns_201(api_client_request, mocker):
    sample_service = create_service(service_permissions=["letter"])
    s3mock = mocker.patch(
        "app.v2.notifications.post_notifications.upload_letter_pdf_parts",
        return_value=["test.pdf", "test.PART2.pdf"],
    )
    mock_send_task = mocker.patch("app.v2.notifications.post_notifications.notify_celery.send_task")
    data = {"reference": "letter-reference", "contents": ["bGV0dGVyLWNvbnRlbnQ=", "bGV0dGVyLWNvbnRlbnQtMg=="]}

    resp_json = api_client_request.post(
        sample_service.id, "v2_notifications.post_precompiled_letter_notification", _data=data
    )

    s3mock.assert_called_once_with(ANY, [b"letter-content", b"letter-content-2"], precompiled=True)

    notification = Notification.query.one()
    assert notification.status == NOTIFICATION_PENDING_VIRUS_CHECK
    assert resp_json == {"id": str(notification.id), "reference": "letter-reference", "postage": notification.postage}

    mock_send_task.assert_called_once_with(
        name=TaskNamesNL.SCAN_LETTER_PARTS,
        kwargs={"filenames": ["test.pdf", "test.PART2.pdf"]},
        queue=QueueNames.ANTIVIRUS,
    )


def test_post_precompiled_letter_notification_rejects_both_content_and_contents(api_client_request):
    sample_service = create_service(service_permissions=["letter"])
    data = {"reference": "letter-reference", "content": "bGV0dGVyLWNvbnRlbnQ=", "contents": ["bGV0dGVyLWNvbnRlbnQ="]}

    resp_json = api_client_request.post(
        sample_service.id, "v2_notifications.post_precompiled_letter_notification", _data=data, _expected_status=400
    )

    assert "exactly one of `content` or `contents`" in resp_json["errors"][0]["message"]
    assert not Notification.query.first()


def test_post_precompiled_letter_notification_rejects_more_than_3_contents(api_client_request):
    sample_service = create_service(service_permissions=["letter"])
    data = {
        "reference": "letter-reference",
        "contents": ["bGV0dGVyLWNvbnRlbnQ="] * 4,
    }

    api_client_request.post(
        sample_service.id, "v2_notifications.post_precompiled_letter_notification", _data=data, _expected_status=400
    )

    assert not Notification.query.first()


def test_post_precompiled_letter_notification_with_contents_and_invalid_base64(api_client_request, mocker):
    sample_service = create_service(service_permissions=["letter"])
    mocker.patch("app.v2.notifications.post_notifications.upload_letter_pdf_parts")

    data = {"reference": "letter-reference", "contents": ["hi"]}

    resp_json = api_client_request.post(
        sample_service.id, "v2_notifications.post_precompiled_letter_notification", _data=data, _expected_status=400
    )

    assert resp_json["errors"][0]["message"] == "Cannot decode letter content (invalid base64 encoding)"
    assert not Notification.query.first()


def test_post_precompiled_letter_notification_with_contents_if_s3_upload_fails_notification_is_not_persisted(
    api_client_request, mocker
):
    sample_service = create_service(service_permissions=["letter"])
    persist_letter_mock = mocker.patch(
        "app.v2.notifications.post_notifications.create_letter_notification", side_effect=create_letter_notification
    )
    s3mock = mocker.patch("app.v2.notifications.post_notifications.upload_letter_pdf_parts", side_effect=Exception())
    mocker.patch("app.v2.notifications.post_notifications.notify_celery.send_task")
    data = {"reference": "letter-reference", "contents": ["bGV0dGVyLWNvbnRlbnQ="]}

    with pytest.raises(expected_exception=Exception):
        api_client_request.post(sample_service.id, "v2_notifications.post_precompiled_letter_notification", _data=data)

    assert s3mock.called
    assert persist_letter_mock.called
    assert Notification.query.count() == 0
