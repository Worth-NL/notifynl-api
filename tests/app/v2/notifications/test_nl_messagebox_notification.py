import base64

import pytest
from faker import Faker
from flask import current_app
from jsonschema import ValidationError

from app.config import QueueNamesNL, TaskNamesNL
from app.constants import MESSAGEBOX_TYPE, NOTIFICATION_CREATED, NOTIFICATION_PENDING_VIRUS_CHECK
from app.models import Notification
from app.notifications.validators import check_rate_limiting
from app.schema_validation import validate
from app.v2.notifications.notification_schemas import post_messagebox_request, post_messagebox_response
from tests.app.db import create_api_key, create_service

fake = Faker()


def _valid_messagebox_data(**overrides):
    data = {
        "sender": str(fake.random_number(digits=32, fix_len=True)),
        "recipient": str(fake.random_number(digits=9, fix_len=True)),
        "message": "This is a messagebox message",
        "subject": "Custom subject",
        "attachments": [
            {"file": base64.b64encode(fake.binary(length=1024)).decode(), "filename": fake.file_name(extension="pdf")}
        ],
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    "data, expected_result",
    [
        (
            {
                "sender": str(fake.random_number(digits=32, fix_len=True)),
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "attachments": [
                    {
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": fake.file_name(extension="pdf"),
                    }
                ],
                "message": "This is a valid message",
            },
            True,
        ),
        (
            {
                "sender": str(fake.random_number(digits=32, fix_len=True)),
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "attachments": [
                    {
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": fake.file_name(extension="pdf"),
                    },
                    {
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": fake.file_name(extension="pdf"),
                    },
                ],
                "subject": "Custom subject",
                "message": "This is also a valid message",
            },
            True,
        ),
        (
            {
                "sender": "invalid",
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "attachments": [
                    {
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": fake.file_name(extension="pdf"),
                    }
                ],
                "message": "This message has an invalid sender",
            },
            False,
        ),
        (
            {
                "sender": str(fake.random_number(digits=32, fix_len=True)),
                "recipient": "invalid",
                "attachments": [
                    {
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": fake.file_name(extension="pdf"),
                    }
                ],
                "message": "This message has an invalid recipient",
            },
            False,
        ),
        (
            {
                "sender": str(fake.random_number(digits=32, fix_len=True)),
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "attachments": [
                    {
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": fake.file_name(extension="pdf"),
                    }
                ],
                # "message": "This is missing the message field",
            },
            False,
        ),
        (
            {
                "sender": str(fake.random_number(digits=32, fix_len=True)),
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "message": "This is missing attachments",
            },
            False,
        ),
        (
            {
                "sender": str(fake.random_number(digits=32, fix_len=True)),
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "attachments": [
                    {
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": fake.file_name(extension="pdf"),
                    },
                    {
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": fake.file_name(extension="pdf"),
                    },
                    {
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": fake.file_name(extension="pdf"),
                    },
                ],
                "subject": "Custom subject",
                "message": "This message has too many attachments",
            },
            False,
        ),
    ],
)
def test_post_messagebox_schema_validation(data, expected_result):
    if expected_result:
        assert validate(data, post_messagebox_request) == data
    else:
        with pytest.raises(ValidationError):
            validate(data, post_messagebox_request)


@pytest.mark.parametrize("reference", [None, "reference_from_client"])
def test_post_messagebox_notification_returns_201(
    mocker, api_client_request, sample_template_with_placeholders, reference
):
    current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"] = "notifynl-test-messagebox-scan"
    mocker.patch("app.messagebox.utils.s3upload")
    mocker.patch("app.v2.notifications.post_notifications_messagebox.notify_celery.send_task")

    data = {
        "sender": str(fake.random_number(digits=32, fix_len=True)),
        "recipient": str(fake.random_number(digits=9, fix_len=True)),
        "message": "This is a messagebox message",
        "attachments": [
            {"file": base64.b64encode(fake.binary(length=1024)).decode(), "filename": fake.file_name(extension="pdf")}
        ],
    }

    if reference:
        data["reference"] = reference

    assert validate(data, post_messagebox_request)

    resp_json = api_client_request.post(
        sample_template_with_placeholders.service_id,
        "v2_notifications.post_notification_messagebox",
        notification_type=MESSAGEBOX_TYPE,
        _data=data,
    )

    assert validate(resp_json, post_messagebox_response) == resp_json

    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].status == NOTIFICATION_PENDING_VIRUS_CHECK
    notification_id = notifications[0].id
    assert resp_json["id"] == str(notification_id)
    assert resp_json.get("organisation_id") is None
    assert f"v2/notifications/{notification_id}" in resp_json["uri"]


def test_post_messagebox_notification_persists_message_and_subject(
    mocker, api_client_request, sample_template_with_placeholders
):
    current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"] = "notifynl-test-messagebox-scan"
    mocker.patch("app.messagebox.utils.s3upload")
    mocker.patch("app.v2.notifications.post_notifications_messagebox.notify_celery.send_task")
    data = _valid_messagebox_data()

    resp_json = api_client_request.post(
        sample_template_with_placeholders.service_id,
        "v2_notifications.post_notification_messagebox",
        notification_type=MESSAGEBOX_TYPE,
        _data=data,
    )

    notification = Notification.query.get(resp_json["id"])
    assert notification.personalisation == {"message": data["message"], "subject": data["subject"]}


def test_post_messagebox_notification_antivirus_disabled_dispatches_deliver(
    mocker, api_client_request, sample_template_with_placeholders
):
    current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"] = "notifynl-test-messagebox-scan"
    current_app.config["ANTIVIRUS_ENABLED"] = False
    mocker.patch("app.messagebox.utils.s3upload")
    mock_send_task = mocker.patch("app.v2.notifications.post_notifications_messagebox.notify_celery.send_task")
    data = _valid_messagebox_data()

    resp_json = api_client_request.post(
        sample_template_with_placeholders.service_id,
        "v2_notifications.post_notification_messagebox",
        notification_type=MESSAGEBOX_TYPE,
        _data=data,
    )

    notification = Notification.query.get(resp_json["id"])
    assert notification.status == NOTIFICATION_CREATED
    mock_send_task.assert_called_once_with(
        name=TaskNamesNL.MESSAGEBOX_DELIVER,
        kwargs={"notification_id": str(notification.id)},
        queue=QueueNamesNL.MESSAGEBOX,
    )


def test_service_messagebox_permissions(sample_service_full_permissions):
    service = sample_service_full_permissions

    assert service.has_permission(MESSAGEBOX_TYPE)


def test_service_messagebox_rate_limiting(mocker):
    mock_rate_limit = mocker.patch("app.notifications.validators.check_service_over_api_rate_limit")
    mock_daily_limit = mocker.patch("app.notifications.validators.check_service_over_daily_message_limit")
    service = create_service(service_permissions=[MESSAGEBOX_TYPE], service_name="Sample messagebox service")
    api_key = create_api_key(service=service)

    check_rate_limiting(service, api_key, notification_type=MESSAGEBOX_TYPE)

    mock_rate_limit.assert_called_once_with(service, api_key.key_type)
    assert mock_daily_limit.call_args_list == [
        mocker.call(service, api_key.key_type, notification_type=MESSAGEBOX_TYPE),
    ]
