from datetime import datetime
from unittest.mock import ANY

import boto3
import pytest
from flask import current_app
from moto import mock_aws

from app import signing
from app.celery.letters_pdf_tasks import (
    get_pdf_for_templated_letter,
    process_sanitised_letter,
    resanitise_pdf,
)
from app.config import QueueNames, TaskNames
from app.constants import (
    INTERNATIONAL_LETTERS,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING_VIRUS_CHECK,
)
from tests.app.db import (
    create_letter_branding,
    create_service,
)


@mock_aws
@pytest.mark.parametrize(
    "key_type, destination_bucket, expected_status, postage, destination_filename",
    [
        (
            KEY_TYPE_NORMAL,
            "S3_BUCKET_LETTERS_PDF",
            NOTIFICATION_CREATED,
            "netherlands",
            "2018-07-01/NOTIFY.FOO.D.1.C.20180701120000.PDF",
        ),
        (
            KEY_TYPE_NORMAL,
            "S3_BUCKET_LETTERS_PDF",
            NOTIFICATION_CREATED,
            "netherlands",
            "2018-07-01/NOTIFY.FOO.D.1.C.20180701120000.PDF",
        ),
        (
            KEY_TYPE_NORMAL,
            "S3_BUCKET_LETTERS_PDF",
            NOTIFICATION_CREATED,
            "europe",
            "2018-07-01/NOTIFY.FOO.D.E.C.20180701120000.PDF",
        ),
        (
            KEY_TYPE_NORMAL,
            "S3_BUCKET_LETTERS_PDF",
            NOTIFICATION_CREATED,
            "rest-of-world",
            "2018-07-01/NOTIFY.FOO.D.N.C.20180701120000.PDF",
        ),
        (
            KEY_TYPE_TEST,
            "S3_BUCKET_TEST_LETTERS",
            NOTIFICATION_DELIVERED,
            "netherlands",
            "NOTIFY.FOO.D.1.C.20180701120000.PDF",
        ),
        (
            KEY_TYPE_TEST,
            "S3_BUCKET_TEST_LETTERS",
            NOTIFICATION_DELIVERED,
            "netherlands",
            "NOTIFY.FOO.D.1.C.20180701120000.PDF",
        ),
    ],
)
def test_process_sanitised_letter_with_valid_letter(
    sample_letter_notification,
    key_type,
    destination_bucket,
    expected_status,
    postage,
    destination_filename,
):
    # We save the letter as if it's 2nd class initially, and the task changes the filename to have the correct postage
    filename = "NOTIFY.FOO.D.2.C.20180701120000.PDF"

    scan_bucket_name = current_app.config["S3_BUCKET_LETTERS_SCAN"]
    template_preview_bucket_name = current_app.config["S3_BUCKET_LETTER_SANITISE"]
    destination_bucket_name = current_app.config[destination_bucket]
    conn = boto3.resource("s3", region_name="eu-west-1")

    scan_bucket = conn.create_bucket(
        Bucket=scan_bucket_name, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"}
    )
    template_preview_bucket = conn.create_bucket(
        Bucket=template_preview_bucket_name, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"}
    )
    destination_bucket = conn.create_bucket(
        Bucket=destination_bucket_name, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"}
    )

    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.put_object(Bucket=scan_bucket_name, Key=filename, Body=b"original_pdf_content")
    s3.put_object(Bucket=template_preview_bucket_name, Key=filename, Body=b"sanitised_pdf_content")

    sample_letter_notification.status = NOTIFICATION_PENDING_VIRUS_CHECK
    sample_letter_notification.key_type = key_type
    sample_letter_notification.billable_units = 1
    sample_letter_notification.created_at = datetime(2018, 7, 1, 12)
    sample_letter_notification.postage = postage

    encoded_data = signing.encode(
        {
            "page_count": 2,
            "message": None,
            "invalid_pages": None,
            "validation_status": "passed",
            "filename": filename,
            "notification_id": str(sample_letter_notification.id),
            "address": "A. User\nThe house on the corner",
        }
    )
    process_sanitised_letter(encoded_data)

    assert sample_letter_notification.status == expected_status
    assert sample_letter_notification.billable_units == 1
    assert sample_letter_notification.to == "A. User\nThe house on the corner"
    assert sample_letter_notification.normalised_to == "a.userthehouseonthecorner"

    assert not list(scan_bucket.objects.all())
    assert not list(template_preview_bucket.objects.all())
    assert len(list(destination_bucket.objects.all())) == 1

    file_contents = conn.Object(destination_bucket_name, destination_filename).get()["Body"].read().decode("utf-8")
    assert file_contents == "sanitised_pdf_content"


@mock_aws
@pytest.mark.parametrize(
    "address, expected_postage, expected_international",
    [
        ("Lady Lou, 123 Main Street, 1234AB City", "netherlands", False),
        ("Lady Lou, 123 Main Street, France", "europe", True),
        ("Lady Lou, 123 Main Street, New Zealand", "rest-of-world", True),
    ],
)
def test_process_sanitised_letter_sets_postage_international(
    sample_letter_notification, expected_postage, expected_international, address
):
    filename = f"NOTIFY.{sample_letter_notification.reference}"

    scan_bucket_name = current_app.config["S3_BUCKET_LETTERS_SCAN"]
    template_preview_bucket_name = current_app.config["S3_BUCKET_LETTER_SANITISE"]
    destination_bucket_name = current_app.config["S3_BUCKET_LETTERS_PDF"]
    conn = boto3.resource("s3", region_name="eu-west-1")
    conn.create_bucket(Bucket=scan_bucket_name, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
    conn.create_bucket(
        Bucket=template_preview_bucket_name, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"}
    )
    conn.create_bucket(Bucket=destination_bucket_name, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})

    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.put_object(Bucket=scan_bucket_name, Key=filename, Body=b"original_pdf_content")
    s3.put_object(Bucket=template_preview_bucket_name, Key=filename, Body=b"sanitised_pdf_content")

    sample_letter_notification.status = NOTIFICATION_PENDING_VIRUS_CHECK
    sample_letter_notification.billable_units = 1
    sample_letter_notification.created_at = datetime(2018, 7, 1, 12)

    encoded_data = signing.encode(
        {
            "page_count": 2,
            "message": None,
            "invalid_pages": None,
            "validation_status": "passed",
            "filename": filename,
            "notification_id": str(sample_letter_notification.id),
            "address": address,
        }
    )
    process_sanitised_letter(encoded_data)

    assert sample_letter_notification.status == "created"
    assert sample_letter_notification.billable_units == 1
    assert sample_letter_notification.to == address
    assert sample_letter_notification.postage == expected_postage
    assert sample_letter_notification.international == expected_international


@pytest.mark.parametrize("branding_name,logo_filename", [(None, None), ["Test Brand", "test-brand"]])
def test_get_pdf_for_templated_letter_happy_path(mocker, sample_letter_notification, branding_name, logo_filename):
    if branding_name:
        letter_branding = create_letter_branding(name=branding_name, filename=logo_filename)
        sample_letter_notification.service.letter_branding = letter_branding
    mock_celery = mocker.patch("app.celery.letters_pdf_tasks.notify_celery.send_task")
    mock_generate_letter_pdf_filename = mocker.patch(
        "app.celery.letters_pdf_tasks.generate_letter_pdf_filename", return_value="LETTER.PDF"
    )
    get_pdf_for_templated_letter(sample_letter_notification.id)

    letter_data = {
        "letter_contact_block": sample_letter_notification.reply_to_text,
        "template": {
            "service": str(sample_letter_notification.service_id),
            "letter_languages": sample_letter_notification.template.letter_languages,
            "subject": sample_letter_notification.template.subject,
            "content": sample_letter_notification.template.content,
            "letter_welsh_subject": sample_letter_notification.template.letter_welsh_subject,
            "letter_welsh_content": sample_letter_notification.template.letter_welsh_content,
            "template_type": sample_letter_notification.template.template_type,
            "letter_attachment": None,
        },
        "values": sample_letter_notification.personalisation,
        "logo_filename": logo_filename,
        "letter_filename": "LETTER.PDF",
        "notification_id": str(sample_letter_notification.id),
        "key_type": sample_letter_notification.key_type,
    }

    mock_celery.assert_called_once_with(
        name=TaskNames.CREATE_PDF_FOR_TEMPLATED_LETTER, args=(ANY,), queue=QueueNames.SANITISE_LETTERS
    )

    actual_data = signing.decode(mock_celery.call_args.kwargs["args"][0])
    assert letter_data == actual_data

    mock_generate_letter_pdf_filename.assert_called_once_with(
        reference=sample_letter_notification.reference,
        created_at=sample_letter_notification.created_at,
        ignore_folder=False,
        postage="netherlands",
    )


@pytest.mark.parametrize(
    "permissions, expected_international_letters_allowed",
    (
        ([LETTER_TYPE], False),
        ([LETTER_TYPE, INTERNATIONAL_LETTERS], True),
    ),
)
def test_resanitise_pdf_calls_template_preview_with_letter_details(
    mocker,
    sample_letter_notification,
    permissions,
    expected_international_letters_allowed,
):
    mock_celery = mocker.patch("app.celery.letters_pdf_tasks.notify_celery.send_task")

    sample_letter_notification.created_at = datetime(2021, 2, 7, 12)
    sample_letter_notification.service = create_service(service_permissions=permissions)

    resanitise_pdf(sample_letter_notification.id)

    mock_celery.assert_called_once_with(
        name=TaskNames.RECREATE_PDF_FOR_PRECOMPILED_LETTER,
        kwargs={
            "notification_id": str(sample_letter_notification.id),
            "file_location": "2021-02-07/NOTIFY.FOO.D.1.C.20210207120000.PDF",
            "allow_international_letters": expected_international_letters_allowed,
        },
        queue=QueueNames.SANITISE_LETTERS,
    )
