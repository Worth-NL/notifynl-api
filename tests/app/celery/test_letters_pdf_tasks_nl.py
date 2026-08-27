from collections import namedtuple
from datetime import UTC, datetime
from unittest.mock import ANY

import boto3
import pytest
from celery.exceptions import MaxRetriesExceededError
from flask import current_app
from freezegun import freeze_time
from moto import mock_aws
from notifications_utils.testing.comparisons import AnyStringMatching

from app import signing
from app.celery.letters_pdf_tasks import (
    LETTER_ATTACHMENTS_VIRUS_SCAN_ERROR_RETRY_DELAY,
    collate_letter_pdfs_to_be_sent,
    get_pdf_for_templated_letter,
    process_sanitised_letter,
    process_virus_scan_error_letter_attachments,
    process_virus_scan_error_letter_parts,
    process_virus_scan_failed_letter_attachments,
    process_virus_scan_failed_letter_parts,
    process_virus_scan_success_letter_attachments,
    resanitise_pdf,
    sanitise_letter_parts,
    send_letters_volume_email_to_dvla,
)
from app.celery.provider_tasks import deliver_email
from app.config import QueueNames, TaskNames, TaskNamesNL
from app.constants import (
    INTERNATIONAL_LETTERS,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING_VIRUS_CHECK,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_VIRUS_SCAN_FAILED,
)
from app.dao import notifications_dao
from app.errors import VirusScanError
from app.exceptions import NotificationTechnicalFailureException
from app.letters.utils import ScanErrorType
from app.models import Notification
from tests.app.conftest import create_custom_template
from tests.app.db import (
    create_letter_branding,
    create_service,
)
from tests.conftest import _with_message_group_id


@pytest.fixture(scope="function")
def letter_volumes_email_template_nl(notify_service):
    email_template_content = "\n".join(
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

    return create_custom_template(
        service=notify_service,
        user=notify_service.users[0],
        template_config_name="LETTERS_VOLUME_EMAIL_TEMPLATE_ID",
        content=email_template_content,
        subject="NotifyNL brievenvolume voor ((date)): ((total_volume)) brieven, ((total_sheets)) vellen",
        template_type="email",
    )


def test_send_letters_volume_email_to_dvla(notify_db_session, mock_celery_task, letter_volumes_email_template_nl):
    MockVolume = namedtuple("LettersVolume", ["postage", "letters_count", "sheets_count"])
    letters_volumes = [
        MockVolume("netherlands", 5, 7),
        MockVolume("europe", 4, 12),
        MockVolume("rest-of-world", 2, 4),
    ]
    send_mock = mock_celery_task(deliver_email)

    send_letters_volume_email_to_dvla(letters_volumes, datetime(2020, 2, 17).date())

    emails_to_dvla = Notification.query.all()
    assert len(emails_to_dvla) == 2
    assert send_mock.call_count == 2
    send_mock.assert_any_call(
        [str(emails_to_dvla[0].id)],
        queue=QueueNames.NOTIFY,
        MessageGroupId=str(emails_to_dvla[0].service_id),
    )
    send_mock.assert_any_call(
        [str(emails_to_dvla[1].id)],
        queue=QueueNames.NOTIFY,
        MessageGroupId=str(emails_to_dvla[1].service_id),
    )
    for email in emails_to_dvla:
        assert str(email.template_id) == current_app.config["LETTERS_VOLUME_EMAIL_TEMPLATE_ID"]
        assert email.to in current_app.config["DVLA_EMAIL_ADDRESSES"]
        assert email.personalisation == {
            "total_volume": 11,
            "netherlands_volume": 5,
            "europe_volume": 4,
            "rest_of_world_volume": 2,
            "total_sheets": 23,
            "netherlands_sheets": 7,
            "europe_sheets": 12,
            "rest_of_world_sheets": 4,
            "date": "17 February 2020",
        }


def test_collate_letter_pdfs_to_be_sent_does_not_send_volume_email_to_dvla(notify_api, notify_db_session, mocker):
    mock_volume_email = mocker.patch("app.celery.letters_pdf_tasks.send_letters_volume_email_to_dvla")
    mock_send_via_api = mocker.patch("app.celery.letters_pdf_tasks.send_dvla_letters_via_api")

    with freeze_time("2021-06-01T17:00+00:00"):
        collate_letter_pdfs_to_be_sent("2021-06-01T16:30:00")

    assert not mock_volume_email.called
    mock_send_via_api.assert_called_once_with(datetime(2021, 6, 1, 17, 30))


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
@pytest.mark.parametrize("letter_address_placement", ["50mm", "60mm", None])
def test_get_pdf_for_templated_letter_happy_path(
    mocker, sample_letter_notification, branding_name, logo_filename, letter_address_placement
):
    if branding_name:
        letter_branding = create_letter_branding(name=branding_name, filename=logo_filename)
        sample_letter_notification.service.letter_branding = letter_branding
    sample_letter_notification.service.letter_address_placement = letter_address_placement
    mock_celery = mocker.patch("app.celery.letters_pdf_tasks.notify_celery.send_task")
    mock_generate_letter_pdf_filename = mocker.patch(
        "app.celery.letters_pdf_tasks.generate_letter_pdf_filename", return_value="LETTER.PDF"
    )
    mocker.patch("app.celery.letters_pdf_tasks.get_letter_attachment_keys", return_value=[])
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
        "letter_address_placement": letter_address_placement,
        "letter_filename": "LETTER.PDF",
        "notification_id": str(sample_letter_notification.id),
        "key_type": sample_letter_notification.key_type,
        "date": AnyStringMatching(
            # There’s a few ms delay between calling the task and creating the datetime here.
            # Celery evades `freeze_time` so the best we can say is the date is close enough
            # to not be in the wrong timezone or format, for example.
            datetime.now(UTC).strftime(r"^%Y-%m-%dT%H:\d{2}:\d{2}\.\d{6}\+00:00$")
        ),
        "attachments": [],
        # sample_letter_template's service has full permissions (incl. INTERNATIONAL_LETTERS)
        "allow_international_letters": True,
    }

    mock_celery.assert_called_once_with(
        name=TaskNames.CREATE_PDF_FOR_TEMPLATED_LETTER,
        args=(ANY,),
        queue=QueueNames.SANITISE_LETTERS,
        MessageGroupId=str(sample_letter_notification.service_id),
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
    "attachment_keys",
    [
        [],
        ["{notification_id}/attachment-1.pdf"],
        ["{notification_id}/attachment-1.pdf", "{notification_id}/attachment-2.pdf"],
    ],
)
def test_get_pdf_for_templated_letter_includes_adhoc_attachment_keys(
    mocker, sample_letter_notification, attachment_keys
):
    expected_keys = [key.format(notification_id=sample_letter_notification.id) for key in attachment_keys]
    mock_celery = mocker.patch("app.celery.letters_pdf_tasks.notify_celery.send_task")
    mocker.patch("app.celery.letters_pdf_tasks.generate_letter_pdf_filename", return_value="LETTER.PDF")
    mocker.patch("app.celery.letters_pdf_tasks.get_letter_attachment_keys", return_value=expected_keys)

    get_pdf_for_templated_letter(sample_letter_notification.id)

    actual_data = signing.decode(mock_celery.call_args.kwargs["args"][0])
    assert actual_data["attachments"] == expected_keys


@pytest.mark.parametrize(
    "permissions, expected_international_letters_allowed",
    (
        ([LETTER_TYPE], False),
        ([LETTER_TYPE, INTERNATIONAL_LETTERS], True),
    ),
)
def test_get_pdf_for_templated_letter_sets_allow_international_letters(
    mocker, sample_letter_notification, permissions, expected_international_letters_allowed
):
    sample_letter_notification.service = create_service(service_permissions=permissions)
    mock_celery = mocker.patch("app.celery.letters_pdf_tasks.notify_celery.send_task")
    mocker.patch("app.celery.letters_pdf_tasks.generate_letter_pdf_filename", return_value="LETTER.PDF")
    mocker.patch("app.celery.letters_pdf_tasks.get_letter_attachment_keys", return_value=[])

    get_pdf_for_templated_letter(sample_letter_notification.id)

    actual_data = signing.decode(mock_celery.call_args.kwargs["args"][0])
    assert actual_data["allow_international_letters"] == expected_international_letters_allowed


def test_process_virus_scan_success_letter_attachments_updates_status_and_dispatches(
    mocker, sample_letter_notification
):
    sample_letter_notification.status = NOTIFICATION_PENDING_VIRUS_CHECK
    mock_get_pdf = mocker.patch("app.celery.letters_pdf_tasks.get_pdf_for_templated_letter.apply_async")

    process_virus_scan_success_letter_attachments(sample_letter_notification.id)

    assert sample_letter_notification.status == NOTIFICATION_CREATED
    mock_get_pdf.assert_called_once_with([str(sample_letter_notification.id)], queue=QueueNames.CREATE_LETTERS_PDF)


def test_process_virus_scan_success_letter_attachments_skips_when_not_pending(mocker, sample_letter_notification):
    notifications_dao.update_notification_status_by_id(sample_letter_notification.id, NOTIFICATION_CREATED)
    mock_get_pdf = mocker.patch("app.celery.letters_pdf_tasks.get_pdf_for_templated_letter.apply_async")

    process_virus_scan_success_letter_attachments(sample_letter_notification.id)

    assert not mock_get_pdf.called


@mock_aws
def test_process_virus_scan_failed_letter_attachments_moves_folder_and_sets_permanent_failure(
    sample_letter_notification, mocker
):
    mock_callback = mocker.patch("app.celery.letters_pdf_tasks.check_and_queue_callback_task")
    scan_bucket = current_app.config["S3_BUCKET_LETTERS_SCAN"]
    invalid_bucket = current_app.config["S3_BUCKET_INVALID_PDF"]
    sample_letter_notification.status = NOTIFICATION_PENDING_VIRUS_CHECK

    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.create_bucket(Bucket=scan_bucket, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
    s3.create_bucket(Bucket=invalid_bucket, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
    s3.put_object(Bucket=scan_bucket, Key=f"{sample_letter_notification.id}/attachment-1.pdf", Body=b"content")

    with pytest.raises(VirusScanError):
        process_virus_scan_failed_letter_attachments(sample_letter_notification.id)

    assert sample_letter_notification.status == NOTIFICATION_VIRUS_SCAN_FAILED
    assert sample_letter_notification.detailed_status_code == "virus-detected"
    mock_callback.assert_called_once_with(sample_letter_notification)


def test_process_virus_scan_error_letter_attachments_reschedules_scan(mocker, sample_letter_notification):
    sample_letter_notification.status = NOTIFICATION_PENDING_VIRUS_CHECK
    mock_send_task = mocker.patch("app.celery.letters_pdf_tasks.notify_celery.send_task")

    process_virus_scan_error_letter_attachments(sample_letter_notification.id)

    mock_send_task.assert_called_once_with(
        name=TaskNamesNL.SCAN_LETTER_ATTACHMENTS,
        kwargs={"notification_id": str(sample_letter_notification.id)},
        queue=QueueNames.ANTIVIRUS,
        countdown=LETTER_ATTACHMENTS_VIRUS_SCAN_ERROR_RETRY_DELAY,
    )


def test_process_virus_scan_error_letter_attachments_skips_reschedule_when_not_pending(
    mocker, sample_letter_notification
):
    notifications_dao.update_notification_status_by_id(sample_letter_notification.id, NOTIFICATION_CREATED)
    mock_send_task = mocker.patch("app.celery.letters_pdf_tasks.notify_celery.send_task")

    process_virus_scan_error_letter_attachments(sample_letter_notification.id)

    assert not mock_send_task.called


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

    with _with_message_group_id(resanitise_pdf, str(sample_letter_notification.service_id)):
        resanitise_pdf(sample_letter_notification.id)

    mock_celery.assert_called_once_with(
        name=TaskNames.RECREATE_PDF_FOR_PRECOMPILED_LETTER,
        kwargs={
            "notification_id": str(sample_letter_notification.id),
            "file_location": "2021-02-07/NOTIFY.FOO.D.1.C.20210207120000.PDF",
            "allow_international_letters": expected_international_letters_allowed,
            "letter_address_placement": sample_letter_notification.service.letter_address_placement,
        },
        queue=QueueNames.SANITISE_LETTERS,
        MessageGroupId=str(sample_letter_notification.service_id),
    )


@pytest.mark.parametrize(
    "permissions, expected_international_letters_allowed",
    (
        ([LETTER_TYPE], False),
        ([LETTER_TYPE, INTERNATIONAL_LETTERS], True),
    ),
)
def test_sanitise_letter_parts_calls_template_preview_sanitise_task(
    mocker,
    sample_letter_notification,
    permissions,
    expected_international_letters_allowed,
):
    mock_celery = mocker.patch("app.celery.letters_pdf_tasks.notify_celery.send_task")
    reference = sample_letter_notification.reference
    filenames = [f"NOTIFY.{reference}", f"NOTIFY.{reference}.PART2"]
    sample_letter_notification.service = create_service(service_permissions=permissions)
    sample_letter_notification.status = NOTIFICATION_PENDING_VIRUS_CHECK

    sanitise_letter_parts(filenames)

    mock_celery.assert_called_once_with(
        name=TaskNamesNL.SANITISE_AND_MERGE_LETTER_PARTS,
        kwargs={
            "notification_id": str(sample_letter_notification.id),
            "filenames": filenames,
            "allow_international_letters": expected_international_letters_allowed,
            "letter_address_placement": sample_letter_notification.service.letter_address_placement,
        },
        queue=QueueNames.SANITISE_LETTERS,
    )


def test_sanitise_letter_parts_does_not_call_template_preview_sanitise_task_if_notification_in_wrong_state(
    mocker,
    sample_letter_notification,
):
    mock_celery = mocker.patch("app.celery.letters_pdf_tasks.notify_celery.send_task")
    filenames = [f"NOTIFY.{sample_letter_notification.reference}"]

    sanitise_letter_parts(filenames)

    assert not mock_celery.called


def test_sanitise_letter_parts_puts_letter_into_technical_failure_if_max_retries_exceeded(
    sample_letter_notification, mocker
):
    mocker.patch("app.celery.letters_pdf_tasks.notify_celery.send_task", side_effect=Exception())
    mocker.patch("app.celery.letters_pdf_tasks.sanitise_letter_parts.retry", side_effect=MaxRetriesExceededError())

    filenames = [f"NOTIFY.{sample_letter_notification.reference}"]
    sample_letter_notification.status = NOTIFICATION_PENDING_VIRUS_CHECK

    with pytest.raises(NotificationTechnicalFailureException):
        sanitise_letter_parts(filenames)

    assert sample_letter_notification.status == NOTIFICATION_TECHNICAL_FAILURE


def test_process_virus_scan_failed_letter_parts_moves_all_parts(sample_letter_notification, mocker):
    mock_callback = mocker.patch("app.celery.letters_pdf_tasks.check_and_queue_callback_task")
    reference = sample_letter_notification.reference
    filenames = [f"NOTIFY.{reference}", f"NOTIFY.{reference}.PART2"]
    sample_letter_notification.status = NOTIFICATION_PENDING_VIRUS_CHECK
    mock_move_failed_pdf = mocker.patch("app.celery.letters_pdf_tasks.move_failed_pdf")

    with pytest.raises(VirusScanError) as e:
        process_virus_scan_failed_letter_parts(filenames)

    assert "Virus scan failed:" in str(e.value)
    assert mock_move_failed_pdf.call_args_list == [
        mocker.call(filenames[0], ScanErrorType.FAILURE),
        mocker.call(filenames[1], ScanErrorType.FAILURE),
    ]
    assert sample_letter_notification.status == NOTIFICATION_VIRUS_SCAN_FAILED
    assert sample_letter_notification.detailed_status_code == "virus-detected"
    mock_callback.assert_called_once_with(sample_letter_notification)


def test_process_virus_scan_error_letter_parts_moves_all_parts(sample_letter_notification, mocker):
    reference = sample_letter_notification.reference
    filenames = [f"NOTIFY.{reference}", f"NOTIFY.{reference}.PART2"]
    sample_letter_notification.status = NOTIFICATION_PENDING_VIRUS_CHECK
    mock_move_failed_pdf = mocker.patch("app.celery.letters_pdf_tasks.move_failed_pdf")

    with pytest.raises(VirusScanError) as e:
        process_virus_scan_error_letter_parts(filenames)

    assert "Virus scan error:" in str(e.value)
    assert mock_move_failed_pdf.call_args_list == [
        mocker.call(filenames[0], ScanErrorType.ERROR),
        mocker.call(filenames[1], ScanErrorType.ERROR),
    ]
    assert sample_letter_notification.status == NOTIFICATION_TECHNICAL_FAILURE
