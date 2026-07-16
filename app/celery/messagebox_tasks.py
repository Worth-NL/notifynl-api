import logging

from flask import current_app
from notifications_utils.s3 import s3_move_folder_between_buckets

from app import ebms_adapter_client, notify_celery
from app.clients.messagebox import MessageboxClientNonRetryableException
from app.config import QueueNames, QueueNamesNL, TaskNamesNL
from app.constants import (
    NOTIFICATION_CREATED,
    NOTIFICATION_SENDING,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_VIRUS_SCAN_FAILED,
)
from app.dao import notifications_dao
from app.errors import VirusScanError
from app.exceptions import NotificationTechnicalFailureException
from app.models import Notification


@notify_celery.task(name=TaskNamesNL.MESSAGEBOX_VIRUS_SCAN_FAILED, bind=True)
def messagebox_virus_scan_failed(self, notification_id: str):
    current_app.logger.info("[%s] [%s]", self.name, notification_id)
    notification: Notification = notifications_dao.get_notification_by_id(notification_id, _raise=True)

    s3_move_folder_between_buckets(
        source_bucket=current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"],
        dest_bucket=current_app.config["S3_BUCKET_MESSAGEBOX_INVALID"],
        folder_name=str(notification.id),
        dest_folder_name=f"FAILURE/{notification.id}",
    )

    notifications_dao.update_notification_status_by_id(notification.id, NOTIFICATION_VIRUS_SCAN_FAILED)

    raise VirusScanError(f"notification id {notification.id} Virus scan failed")


@notify_celery.task(name=TaskNamesNL.MESSAGEBOX_VIRUS_SCAN_ERROR, bind=True)
def messagebox_virus_scan_error(self, notification_id: str):
    current_app.logger.info("[%s] [%s]", self.name, notification_id)
    notification: Notification = notifications_dao.get_notification_by_id(notification_id, _raise=True)

    s3_move_folder_between_buckets(
        source_bucket=current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"],
        dest_bucket=current_app.config["S3_BUCKET_MESSAGEBOX_INVALID"],
        folder_name=str(notification.id),
        dest_folder_name=f"ERROR/{notification.id}",
    )

    notifications_dao.update_notification_status_by_id(notification.id, NOTIFICATION_TECHNICAL_FAILURE)

    raise VirusScanError(f"notification id {notification.id} Virus scan error")


@notify_celery.task(name=TaskNamesNL.MESSAGEBOX_VIRUS_SCAN_SUCCESS, bind=True)
def messagebox_virus_scan_success(self, notification_id: str):
    current_app.logger.info("[%s] [%s]", self.name, notification_id)
    notification: Notification = notifications_dao.get_notification_by_id(notification_id, _raise=True)

    s3_move_folder_between_buckets(
        source_bucket=current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"],
        dest_bucket=current_app.config["S3_BUCKET_MESSAGEBOX_ATTACHMENTS"],
        folder_name=str(notification.id),
    )

    notifications_dao.update_notification_status_by_id(notification.id, NOTIFICATION_CREATED)

    notify_celery.send_task(
        name=TaskNamesNL.MESSAGEBOX_DELIVER,
        kwargs={"notification_id": str(notification.id)},
        queue=QueueNamesNL.MESSAGEBOX,
    )


@notify_celery.task(
    name=TaskNamesNL.MESSAGEBOX_DELIVER,
    bind=True,
    max_retries=48,
    default_retry_delay=300,
    early_log_level=logging.DEBUG,
)
def messagebox_deliver(self, notification_id: str):
    current_app.logger.info("[%s] [%s]", self.name, notification_id)
    notification: Notification = notifications_dao.get_notification_by_id(notification_id, _raise=True)

    if notification.status != NOTIFICATION_CREATED:
        # Mirrors send_sms_to_provider/send_email_to_provider's idempotency guard
        # (app/delivery/send_to_providers.py): a re-dispatch of this task after the
        # notification already moved past "created" (e.g. a duplicate/stale trigger)
        # must be a safe no-op, not a resend -- ebms-core rejects a resend with the
        # same BerichtID as BerichtBestaatAl, and resending races the real async result.
        current_app.logger.info(
            "[%s] [%s] notification already in status %s, not resending",
            self.name,
            notification_id,
            notification.status,
        )
        return

    try:
        envelope_message_id = ebms_adapter_client.send_messagebox(str(notification.id))
    except MessageboxClientNonRetryableException as e:
        current_app.logger.exception("Messagebox notification %s failed: %s", notification_id, e)
        notifications_dao.update_notification_status_by_id(notification.id, NOTIFICATION_TECHNICAL_FAILURE)
        return
    except Exception:
        current_app.logger.exception("RETRY: Messagebox notification %s failed", notification_id)
        try:
            self.retry(queue=QueueNames.RETRY)
        except self.MaxRetriesExceededError as retry_exc:
            message = (
                "RETRY FAILED: Max retries reached. The task messagebox_deliver failed for "
                f"notification {notification_id}. Notification has been updated to technical-failure"
            )
            notifications_dao.update_notification_status_by_id(notification.id, NOTIFICATION_TECHNICAL_FAILURE)
            raise NotificationTechnicalFailureException(message) from retry_exc
        return

    notifications_dao.update_notification_status_by_id(notification.id, NOTIFICATION_SENDING)
    notification.reference = envelope_message_id
    notifications_dao.dao_update_notification(notification)
