from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from celery.exceptions import MaxRetriesExceededError
from flask import current_app
from freezegun import freeze_time
from moto import mock_aws
from notifications_utils.recipient_validation.notifynl.postal_address import PostalAddress
from pytest_mock import MockerFixture

from app.celery.provider_tasks import (
    deliver_letter,
    deliver_sms,
)
from app.constants import (
    NOTIFICATION_CREATED,
    NOTIFICATION_SENDING,
)
from app.exceptions import NotificationTechnicalFailureException
from app.models import Template
from app.otel_metrics.notification import _send_duration
from tests.app.db import create_notification


@mock_aws
@freeze_time("2020-02-17 16:00:00")
def test_deliver_letter(
    mocker,
    sample_letter_template,
    sample_organisation,
):
    mock_send_letter = mocker.patch("app.celery.provider_tasks.dvla_client.send_letter")
    mocker.patch("app.celery.provider_tasks._get_callback_url", return_value="example.com?token=1")

    letter = create_notification(
        template=sample_letter_template,
        to_field="A. User\nMy Street,\n1234AB city",
        personalisation={"address_line_1": "Provided as PDF"},
        status=NOTIFICATION_CREATED,
        reference="ref1",
        client_reference="client_ref1",
        created_at=datetime.now(),
    )
    sample_letter_template.service.organisation = sample_organisation

    pdf_bucket = current_app.config["S3_BUCKET_LETTERS_PDF"]
    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.create_bucket(Bucket=pdf_bucket, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
    s3.put_object(Bucket=pdf_bucket, Key="2020-02-17/NOTIFY.REF1.D.1.C.20200217150000.PDF", Body=b"file")

    deliver_letter(letter.id)

    mock_send_letter.assert_called_once_with(
        notification_id=str(letter.id),
        reference="ref1",
        client_reference="client_ref1",
        address=PostalAddress("A. User\nMy Street\n1234AB city", True),
        postage="netherlands",
        service_id=str(letter.service_id),
        organisation_id=str(sample_organisation.id),
        pdf_file=b"file",
        callback_url="example.com?token=1",
    )
    assert letter.status == NOTIFICATION_SENDING
    assert letter.sent_by == "dvla"


@freeze_time("2026-01-01 09:00:00")
@pytest.mark.parametrize(
    "key_type, phone_number, international, country_code, should_raise",
    [
        ("normal", "+447700900855", False, "44", False),
        ("normal", "+15555550199", True, "1", False),
        ("test", "+447700900855", False, "44", False),
        ("normal", "+447700900855", False, "44", True),
    ],
)
def test_deliver_sms_records_duration_histogram(
    mocker: MockerFixture,
    sample_template: Template,
    key_type: str,
    phone_number: str,
    international: bool,
    country_code: str,
    should_raise: bool,
) -> None:
    record_send_duration_mock = mocker.patch.object(_send_duration, "record")
    mocker.patch("app.celery.provider_tasks.deliver_sms.retry", side_effect=MaxRetriesExceededError())
    mocker.patch("app.delivery.send_to_providers.send_sms_response")
    mocker.patch("app.spryng_client.send_sms", side_effect=RuntimeError() if should_raise else None)

    notification = create_notification(
        template=sample_template,
        to_field=phone_number,
        international=international,
        phone_prefix=country_code,
        key_type=key_type,
        created_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    with pytest.raises(NotificationTechnicalFailureException) if should_raise else nullcontext():
        deliver_sms(notification.id)

    expected_attributes = {
        "key.type": key_type,
        "notification.type": "sms",
        "provider.name": "spryng",
    }

    if should_raise:
        expected_attributes["error.type"] = "builtins.RuntimeError"

    record_send_duration_mock.assert_called_once_with(
        60.0,
        expected_attributes,
    )
