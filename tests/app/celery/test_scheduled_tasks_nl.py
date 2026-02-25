from datetime import datetime, timedelta
from unittest import mock
from unittest.mock import ANY, call

from freezegun import freeze_time
from notifications_utils.clients.zendesk.zendesk_client import (
    NotifySupportTicket,
    NotifyTicketType,
)

from app.celery.scheduled_tasks import (
    check_for_missing_rows_in_completed_jobs,
    check_if_letters_still_pending_virus_check,
)
from app.celery.tasks import save_email
from app.config import QueueNames, TaskNames
from app.constants import (
    JOB_STATUS_FINISHED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING_VIRUS_CHECK,
)
from tests.app import load_example_csv
from tests.app.db import (
    create_job,
    create_notification,
)


@freeze_time("2019-05-30 14:00:00")
def test_check_if_letters_still_pending_virus_check_raises_zendesk_if_files_cant_be_found(
    sample_letter_template, mocker
):
    mock_file_exists = mocker.patch("app.aws.s3.file_exists", return_value=False)
    mock_create_ticket = mocker.spy(NotifySupportTicket, "__init__")
    mock_celery = mocker.patch("app.celery.scheduled_tasks.notify_celery.send_task")
    mock_send_ticket_to_zendesk = mocker.patch(
        "app.celery.scheduled_tasks.zendesk_client.send_ticket_to_zendesk",
        autospec=True,
    )

    create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(seconds=600),
        reference="ignore as still has time",
    )
    create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_DELIVERED,
        created_at=datetime.utcnow() - timedelta(seconds=1000),
        reference="ignore as status in delivered",
    )
    notification_1 = create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(seconds=601),
        reference="one",
    )
    notification_2 = create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(seconds=1000),
        reference="two",
    )

    check_if_letters_still_pending_virus_check()

    assert mock_file_exists.call_count == 2
    mock_file_exists.assert_has_calls(
        [
            call("test-letters-scan", "NOTIFY.ONE.D.1.C.20190530134959.PDF"),
            call("test-letters-scan", "NOTIFY.TWO.D.1.C.20190530134320.PDF"),
        ],
        any_order=True,
    )
    assert mock_celery.called is False

    mock_create_ticket.assert_called_once_with(
        ANY,
        subject="[test] Letters still pending virus check",
        message=ANY,
        ticket_type="task",
        notify_ticket_type=NotifyTicketType.TECHNICAL,
        notify_task_type="notify_task_letters_pending_scan",
    )
    assert "2 precompiled letters have been pending-virus-check" in mock_create_ticket.call_args.kwargs["message"]
    assert f"{(str(notification_1.id), notification_1.reference)}" in mock_create_ticket.call_args.kwargs["message"]
    assert f"{(str(notification_2.id), notification_2.reference)}" in mock_create_ticket.call_args.kwargs["message"]
    mock_send_ticket_to_zendesk.assert_called_once()


@freeze_time("2019-05-30 14:00:00")
def test_check_if_letters_still_pending_virus_check_restarts_scan_for_stuck_letters(mocker, sample_letter_template):
    mock_file_exists = mocker.patch("app.aws.s3.file_exists", return_value=True)
    mock_create_ticket = mocker.spy(NotifySupportTicket, "__init__")
    mock_celery = mocker.patch("app.celery.scheduled_tasks.notify_celery.send_task")

    create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(minutes=10, seconds=1),
        reference="one",
    )
    create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(minutes=9, seconds=59),
        reference="still has time to send",
    )
    create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(minutes=30, seconds=1),
        reference="too old for us to bother with",
    )
    expected_filename = "NOTIFY.ONE.D.1.C.20190530134959.PDF"

    check_if_letters_still_pending_virus_check()

    mock_file_exists.assert_called_once_with("test-letters-scan", expected_filename)

    mock_celery.assert_called_once_with(
        name=TaskNames.SCAN_FILE, kwargs={"filename": expected_filename}, queue=QueueNames.ANTIVIRUS
    )

    assert mock_create_ticket.called is False


def test_check_for_missing_rows_in_completed_jobs(mocker, sample_email_template, mock_celery_task):
    job = create_job(
        template=sample_email_template,
        notification_count=5,
        job_status=JOB_STATUS_FINISHED,
        processing_finished=datetime.utcnow() - timedelta(minutes=20),
    )
    for i in range(4):
        create_notification(job=job, job_row_number=i)

    mocker.patch(
        "app.celery.tasks.s3.get_job_and_metadata_from_s3",
        return_value=(load_example_csv("multiple_email"), {"sender_id": None}),
    )
    mock_encode = mocker.patch("app.signing.encode", return_value="something_encoded")
    mocker.patch("app.celery.tasks.create_uuid", return_value="some-uuid")
    mock_save_email = mock_celery_task(save_email)

    check_for_missing_rows_in_completed_jobs()

    assert mock_encode.mock_calls == [
        mock.call(
            {
                "template": str(job.template_id),
                "template_version": job.template_version,
                "job": str(job.id),
                "to": "test5@test.com",
                "row_number": 4,
                "personalisation": {"emailaddress": "test5@test.com"},
                "client_reference": None,
            }
        )
    ]
    assert mock_save_email.mock_calls == [
        mock.call((str(job.service_id), "some-uuid", "something_encoded"), {}, queue="database-tasks")
    ]


def test_check_for_missing_rows_in_completed_jobs_uses_sender_id(
    mocker, sample_email_template, fake_uuid, mock_celery_task
):
    job = create_job(
        template=sample_email_template,
        notification_count=5,
        job_status=JOB_STATUS_FINISHED,
        processing_finished=datetime.utcnow() - timedelta(minutes=20),
    )
    for i in range(4):
        create_notification(job=job, job_row_number=i)

    mocker.patch(
        "app.celery.tasks.s3.get_job_and_metadata_from_s3",
        return_value=(load_example_csv("multiple_email"), {"sender_id": fake_uuid}),
    )
    mock_encode = mocker.patch("app.signing.encode", return_value="something_encoded")
    mocker.patch("app.celery.tasks.create_uuid", return_value="some-uuid")
    mock_save_email = mock_celery_task(save_email)

    check_for_missing_rows_in_completed_jobs()

    assert mock_encode.mock_calls == [
        mock.call(
            {
                "template": str(job.template_id),
                "template_version": job.template_version,
                "job": str(job.id),
                "to": "test5@test.com",
                "row_number": 4,
                "personalisation": {"emailaddress": "test5@test.com"},
                "client_reference": None,
            }
        )
    ]
    assert mock_save_email.mock_calls == [
        mock.call(
            (str(job.service_id), "some-uuid", "something_encoded"), {"sender_id": fake_uuid}, queue="database-tasks"
        )
    ]
