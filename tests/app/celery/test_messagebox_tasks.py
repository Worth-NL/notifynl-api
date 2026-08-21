import boto3
import pytest
from celery.exceptions import MaxRetriesExceededError
from moto import mock_aws

from app.celery import messagebox_tasks
from app.celery.messagebox_tasks import (
    MESSAGEBOX_VIRUS_SCAN_ERROR_RETRY_DELAY,
    messagebox_deliver,
    messagebox_virus_scan_error,
    messagebox_virus_scan_failed,
    messagebox_virus_scan_success,
)
from app.clients.messagebox import MessageboxClientNonRetryableException
from app.config import QueueNames, QueueNamesNL, TaskNamesNL
from app.constants import (
    MESSAGEBOX_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_PENDING_VIRUS_CHECK,
    NOTIFICATION_SENDING,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_VIRUS_SCAN_FAILED,
)
from app.dao import notifications_dao
from app.dao.templates_messagebox_dao import get_messagebox_template
from app.errors import VirusScanError
from app.exceptions import NotificationTechnicalFailureException
from tests.app.db import create_notification, create_service


@pytest.fixture
def messagebox_notification(notify_db_session, notify_user):
    service = create_service(service_permissions=[MESSAGEBOX_TYPE])
    template = get_messagebox_template(service.id)
    notification = create_notification(template=template, status="pending-virus-check")
    return notification


@pytest.fixture(autouse=True)
def ebms_adapter_config():
    # The ebms_adapter_client LocalProxy is instantiated lazily on first
    # access (including by mocker.patch itself), and its __init__ requires
    # this key -- the plain "test" config (as opposed to "testnl") doesn't
    # define it, so it must be set before any test in this module touches
    # the proxy.
    messagebox_tasks.current_app.config["EBMS_BERICHTENBOX_CPA_ID"] = "test-cpa"


@mock_aws
def test_messagebox_virus_scan_success_moves_files_and_dispatches_deliver(mocker, messagebox_notification):
    scan_bucket = "notifynl-test-messagebox-scan"
    attachments_bucket = "notifynl-test-messagebox-attachments"
    messagebox_tasks.current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"] = scan_bucket
    messagebox_tasks.current_app.config["S3_BUCKET_MESSAGEBOX_ATTACHMENTS"] = attachments_bucket

    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.create_bucket(Bucket=scan_bucket, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
    s3.create_bucket(Bucket=attachments_bucket, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
    s3.put_object(Bucket=scan_bucket, Key=f"{messagebox_notification.id}/file.pdf", Body=b"content")

    mock_send_task = mocker.patch("app.celery.messagebox_tasks.notify_celery.send_task")

    messagebox_virus_scan_success(messagebox_notification.id)

    assert messagebox_notification.status == NOTIFICATION_CREATED
    mock_send_task.assert_called_once_with(
        name=TaskNamesNL.MESSAGEBOX_DELIVER,
        kwargs={"notification_id": str(messagebox_notification.id)},
        queue=QueueNamesNL.MESSAGEBOX,
    )


@mock_aws
def test_messagebox_virus_scan_failed_sets_permanent_failure(mocker, messagebox_notification):
    # A confirmed virus match is final -- unlike a scan error, it must never be retried.
    scan_bucket = "notifynl-test-messagebox-scan"
    invalid_bucket = "notifynl-test-messagebox-invalid"
    messagebox_tasks.current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"] = scan_bucket
    messagebox_tasks.current_app.config["S3_BUCKET_MESSAGEBOX_INVALID"] = invalid_bucket

    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.create_bucket(Bucket=scan_bucket, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
    s3.create_bucket(Bucket=invalid_bucket, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
    s3.put_object(Bucket=scan_bucket, Key=f"{messagebox_notification.id}/file.pdf", Body=b"content")

    with pytest.raises(VirusScanError):
        messagebox_virus_scan_failed(messagebox_notification.id)

    assert messagebox_notification.status == NOTIFICATION_VIRUS_SCAN_FAILED


def test_messagebox_virus_scan_error_reschedules_scan(mocker, messagebox_notification):
    # A scan error is a transient infra issue (e.g. clamd unreachable), not a virus verdict --
    # it must be retried later, not treated as a permanent failure.
    mock_send_task = mocker.patch("app.celery.messagebox_tasks.notify_celery.send_task")

    messagebox_virus_scan_error(messagebox_notification.id)

    assert messagebox_notification.status == NOTIFICATION_PENDING_VIRUS_CHECK
    mock_send_task.assert_called_once_with(
        name=TaskNamesNL.MESSAGEBOX_SCAN_ATTACHMENTS,
        kwargs={"notification_id": str(messagebox_notification.id)},
        queue=QueueNames.ANTIVIRUS,
        countdown=MESSAGEBOX_VIRUS_SCAN_ERROR_RETRY_DELAY,
    )


def test_messagebox_virus_scan_error_skips_reschedule_when_not_pending(mocker, messagebox_notification):
    notifications_dao.update_notification_status_by_id(messagebox_notification.id, NOTIFICATION_CREATED)
    mock_send_task = mocker.patch("app.celery.messagebox_tasks.notify_celery.send_task")

    messagebox_virus_scan_error(messagebox_notification.id)

    mock_send_task.assert_not_called()
    assert messagebox_notification.status == NOTIFICATION_CREATED


def test_messagebox_deliver_success_sets_sending_and_stores_reference(mocker, messagebox_notification):
    notifications_dao.update_notification_status_by_id(messagebox_notification.id, NOTIFICATION_CREATED)
    mocker.patch("app.celery.messagebox_tasks.ebms_adapter_client.send_messagebox", return_value="envelope-id-1")

    messagebox_deliver(messagebox_notification.id)

    assert messagebox_notification.status == NOTIFICATION_SENDING
    assert messagebox_notification.reference == "envelope-id-1"


def test_messagebox_deliver_non_retryable_failure_sets_technical_failure(mocker, messagebox_notification):
    notifications_dao.update_notification_status_by_id(messagebox_notification.id, NOTIFICATION_CREATED)
    mocker.patch(
        "app.celery.messagebox_tasks.ebms_adapter_client.send_messagebox",
        side_effect=MessageboxClientNonRetryableException("bad payload"),
    )
    mock_retry = mocker.patch("app.celery.messagebox_tasks.messagebox_deliver.retry")

    messagebox_deliver(messagebox_notification.id)

    assert mock_retry.called is False
    assert messagebox_notification.status == NOTIFICATION_TECHNICAL_FAILURE


def test_messagebox_deliver_retries_on_retryable_failure(mocker, messagebox_notification):
    notifications_dao.update_notification_status_by_id(messagebox_notification.id, NOTIFICATION_CREATED)
    mocker.patch("app.celery.messagebox_tasks.ebms_adapter_client.send_messagebox", side_effect=Exception("boom"))
    mock_retry = mocker.patch("app.celery.messagebox_tasks.messagebox_deliver.retry")

    messagebox_deliver(messagebox_notification.id)

    assert mock_retry.called is True
    assert messagebox_notification.status == NOTIFICATION_CREATED


def test_messagebox_deliver_max_retries_exceeded_sets_technical_failure(mocker, messagebox_notification):
    notifications_dao.update_notification_status_by_id(messagebox_notification.id, NOTIFICATION_CREATED)
    mocker.patch("app.celery.messagebox_tasks.ebms_adapter_client.send_messagebox", side_effect=Exception("boom"))
    mocker.patch("app.celery.messagebox_tasks.messagebox_deliver.retry", side_effect=MaxRetriesExceededError())

    with pytest.raises(NotificationTechnicalFailureException) as exc_info:
        messagebox_deliver(messagebox_notification.id)

    assert str(messagebox_notification.id) in str(exc_info.value)
    assert messagebox_notification.status == NOTIFICATION_TECHNICAL_FAILURE


def test_messagebox_deliver_skips_resend_when_not_created(mocker, messagebox_notification):
    notifications_dao.update_notification_status_by_id(messagebox_notification.id, NOTIFICATION_CREATED)
    notifications_dao.update_notification_status_by_id(messagebox_notification.id, NOTIFICATION_SENDING)
    messagebox_notification.reference = "envelope-id-1"
    notifications_dao.dao_update_notification(messagebox_notification)
    mock_send = mocker.patch("app.celery.messagebox_tasks.ebms_adapter_client.send_messagebox")

    messagebox_deliver(messagebox_notification.id)

    mock_send.assert_not_called()
    assert messagebox_notification.status == NOTIFICATION_SENDING
    assert messagebox_notification.reference == "envelope-id-1"
