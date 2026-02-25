from datetime import datetime

import boto3
from flask import current_app
from freezegun import freeze_time
from moto import mock_aws
from notifications_utils.recipient_validation.notifynl.postal_address import PostalAddress

from app.celery.provider_tasks import (
    deliver_letter,
)
from app.constants import (
    NOTIFICATION_CREATED,
    NOTIFICATION_SENDING,
)
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
        address=PostalAddress("A. User\nMy Street\n1234AB city", True),
        postage="netherlands",
        service_id=str(letter.service_id),
        organisation_id=str(sample_organisation.id),
        pdf_file=b"file",
        callback_url="example.com?token=1",
    )
    assert letter.status == NOTIFICATION_SENDING
    assert letter.sent_by == "dvla"
