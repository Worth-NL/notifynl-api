import base64

import pytest
from ebms_adapter_client.berichtenbox import MAX_PERSONALISED_ATTACHMENT_BYTES
from faker import Faker
from flask import current_app
from jsonschema import ValidationError

from app import encryption
from app.config import QueueNamesNL, TaskNamesNL
from app.constants import MESSAGEBOX_TYPE, NOTIFICATION_CREATED, NOTIFICATION_PENDING_VIRUS_CHECK
from app.dao.organisation_dao import dao_add_service_to_organisation
from app.models import Notification
from app.notifications.validators import check_rate_limiting
from app.schema_validation import validate
from app.v2.notifications.notification_schemas import post_messagebox_request, post_messagebox_response
from tests.app.db import create_api_key, create_organisation, create_service

fake = Faker()


def _valid_messagebox_data(**overrides):
    data = {
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
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "message": "This has no attachments at all, which is now valid",
            },
            True,
        ),
        (
            {
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "attachments": [],
                "message": "This has an explicitly empty attachments list, which is also valid",
            },
            True,
        ),
        (
            {
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
        (
            {
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "attachments": [
                    {
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": fake.file_name(extension="pdf"),
                    }
                ],
                # Logius caps Onderwerp (subject) at 50 characters -- a longer value passes
                # our schema without this and fails the ebms-core XSD instead, unrecoverably.
                "subject": "x" * 51,
                "message": "This message has a subject that is too long",
            },
            False,
        ),
        (
            {
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "attachments": [
                    {
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": fake.file_name(extension="pdf"),
                    }
                ],
                # Logius caps Berichttekst (message) at 4000 characters.
                "message": "x" * 4_001,
            },
            False,
        ),
        (
            {
                # GebruikerID (BSN) must be all digits -- a same-length non-numeric
                # value used to pass our schema and fail at ebms-core instead.
                "recipient": "12345678a",
                "attachments": [
                    {
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": fake.file_name(extension="pdf"),
                    }
                ],
                "message": "This message has a non-numeric recipient",
            },
            False,
        ),
        (
            {
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "attachments": [
                    {
                        # Logius caps Omschrijving (attachment filename/description) at
                        # 128 characters.
                        "file": base64.b64encode(fake.binary(length=1024)).decode(),
                        "filename": "x" * 129 + ".pdf",
                    }
                ],
                "message": "This message has a filename that is too long",
            },
            False,
        ),
        (
            {
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "message": "This message overrides the default BerichtType",
                "message_type": "custom-type",
            },
            True,
        ),
        (
            {
                "recipient": str(fake.random_number(digits=9, fix_len=True)),
                "message": "This message has an unknown top-level field",
                "berichttype": "custom-type",
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
    sample_template_with_placeholders.service.oin = str(fake.random_number(digits=20, fix_len=True))
    current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"] = "notifynl-test-messagebox-scan"
    mocker.patch("app.messagebox.utils.s3upload")
    mocker.patch("app.v2.notifications.post_notifications_messagebox.notify_celery.send_task")

    data = {
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


def test_post_messagebox_notification_returns_organisation_id_as_plain_string(
    mocker, api_client_request, sample_template_with_placeholders
):
    sample_template_with_placeholders.service.oin = str(fake.random_number(digits=20, fix_len=True))
    current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"] = "notifynl-test-messagebox-scan"
    mocker.patch("app.messagebox.utils.s3upload")
    mocker.patch("app.v2.notifications.post_notifications_messagebox.notify_celery.send_task")

    organisation = create_organisation()
    dao_add_service_to_organisation(service=sample_template_with_placeholders.service, organisation_id=organisation.id)

    data = _valid_messagebox_data()

    resp_json = api_client_request.post(
        sample_template_with_placeholders.service_id,
        "v2_notifications.post_notification_messagebox",
        notification_type=MESSAGEBOX_TYPE,
        _data=data,
    )

    assert validate(resp_json, post_messagebox_response) == resp_json
    assert resp_json["organisation_id"] == str(organisation.id)


def test_post_messagebox_notification_persists_message_and_subject(
    mocker, api_client_request, sample_template_with_placeholders
):
    sample_template_with_placeholders.service.oin = str(fake.random_number(digits=20, fix_len=True))
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
    assert notification.personalisation == {
        "message": data["message"],
        "subject": data["subject"],
        "message_type": None,
    }


def test_post_messagebox_notification_persists_message_type_override(
    mocker, api_client_request, sample_template_with_placeholders
):
    sample_template_with_placeholders.service.oin = str(fake.random_number(digits=20, fix_len=True))
    current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"] = "notifynl-test-messagebox-scan"
    mocker.patch("app.messagebox.utils.s3upload")
    mocker.patch("app.v2.notifications.post_notifications_messagebox.notify_celery.send_task")
    data = _valid_messagebox_data(message_type="custom-type")

    resp_json = api_client_request.post(
        sample_template_with_placeholders.service_id,
        "v2_notifications.post_notification_messagebox",
        notification_type=MESSAGEBOX_TYPE,
        _data=data,
    )

    notification = Notification.query.get(resp_json["id"])
    assert notification.personalisation["message_type"] == "custom-type"


def test_post_messagebox_notification_encrypts_recipient_bsn(
    mocker, api_client_request, sample_template_with_placeholders
):
    sample_template_with_placeholders.service.oin = str(fake.random_number(digits=20, fix_len=True))
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

    assert notification.to != data["recipient"]

    # This mirrors exactly how the original bug was found: the old sign-only
    # itsdangerous token could be recovered by bare base64 decoding, no secret
    # key needed at all -- the replacement must not share that flaw.
    raw = base64.urlsafe_b64decode(notification.to)
    assert data["recipient"].encode() not in raw

    assert encryption.decrypt(notification.to) == data["recipient"]


def test_post_messagebox_notification_with_test_key_wipes_recipient_immediately(
    mocker, api_client_request, sample_template_with_placeholders
):
    # Test-key sends are persisted already-delivered (see `status` in
    # process_messagebox_notification) and never pass through
    # _update_notification_status, so the BSN must be wiped at creation time
    # instead -- the zero-retention-after-terminal-state guarantee is
    # unconditional, not just for real (non-test-key) sends.
    sample_template_with_placeholders.service.oin = str(fake.random_number(digits=20, fix_len=True))
    current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"] = "notifynl-test-messagebox-scan"
    mocker.patch("app.messagebox.utils.s3upload")
    mocker.patch("app.v2.notifications.post_notifications_messagebox.notify_celery.send_task")
    data = _valid_messagebox_data()

    resp_json = api_client_request.post(
        sample_template_with_placeholders.service_id,
        "v2_notifications.post_notification_messagebox",
        _api_key_type="test",
        notification_type=MESSAGEBOX_TYPE,
        _data=data,
    )

    notification = Notification.query.get(resp_json["id"])
    assert notification.status == "delivered"
    assert notification.to is None
    assert notification.normalised_to is None


def test_post_messagebox_notification_antivirus_disabled_dispatches_deliver(
    mocker, api_client_request, sample_template_with_placeholders
):
    sample_template_with_placeholders.service.oin = str(fake.random_number(digits=20, fix_len=True))
    mocker.patch.dict(
        current_app.config, {"S3_BUCKET_MESSAGEBOX_SCAN": "notifynl-test-messagebox-scan", "ANTIVIRUS_ENABLED": False}
    )
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


def test_messagebox_attachments_over_combined_size_limit_are_rejected(
    mocker, api_client_request, sample_template_with_placeholders
):
    sample_template_with_placeholders.service.oin = str(fake.random_number(digits=20, fix_len=True))
    current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"] = "notifynl-test-messagebox-scan"
    mocker.patch("app.messagebox.utils.s3upload")
    mocker.patch("app.v2.notifications.post_notifications_messagebox.notify_celery.send_task")

    # MAX_PERSONALISED_ATTACHMENT_BYTES is measured before base64 encoding --
    # one attachment alone over that raw size must be rejected.
    oversized_content = b"x" * (MAX_PERSONALISED_ATTACHMENT_BYTES + 1)
    data = _valid_messagebox_data(
        attachments=[{"file": base64.b64encode(oversized_content).decode(), "filename": "big.pdf"}]
    )

    resp_json = api_client_request.post(
        sample_template_with_placeholders.service_id,
        "v2_notifications.post_notification_messagebox",
        notification_type=MESSAGEBOX_TYPE,
        _data=data,
        _expected_status=400,
    )

    assert "Combined attachment size" in resp_json["errors"][0]["message"]
