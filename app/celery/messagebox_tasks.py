import logging

import sentry_sdk
from flask import current_app
from notifications_utils.s3 import s3_move_folder_between_buckets

from app import ebms_adapter_client, notify_celery
from app.clients.messagebox import MessageboxClientNonRetryableException
from app.config import QueueNames, QueueNamesNL, TaskNamesNL
from app.constants import (
    NOTIFICATION_CREATED,
    NOTIFICATION_PENDING_VIRUS_CHECK,
    NOTIFICATION_SENDING,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_VIRUS_SCAN_FAILED,
)
from app.dao import notifications_dao
from app.errors import VirusScanError
from app.exceptions import NotificationTechnicalFailureException
from app.models import Notification
from app.notifications.notifications_ses_callback import check_and_queue_callback_task


@notify_celery.task(name=TaskNamesNL.MESSAGEBOX_VIRUS_SCAN_FAILED, bind=True)
def messagebox_virus_scan_failed(self, notification_id: str):
    sentry_sdk.set_tag("notification_id", notification_id)
    current_app.logger.info("[%s] [%s]", self.name, notification_id, extra={"notification_id": notification_id})
    notification: Notification = notifications_dao.get_notification_by_id(notification_id, _raise=True)

    s3_move_folder_between_buckets(
        source_bucket=current_app.config["S3_BUCKET_MESSAGEBOX_SCAN"],
        dest_bucket=current_app.config["S3_BUCKET_MESSAGEBOX_INVALID"],
        folder_name=str(notification.id),
        dest_folder_name=f"FAILURE/{notification.id}",
    )

    updated_notification = notifications_dao.update_notification_status_by_id(
        notification.id, NOTIFICATION_VIRUS_SCAN_FAILED, detailed_status_code="virus-detected"
    )
    # [NOTIFYNL] update_notification_status_by_id returns None if the notification is no
    # longer in an eligible pre-callback status (e.g. this task is invoked a second time
    # for the same notification) - guard against passing None into check_and_queue_callback_task.
    if updated_notification:
        check_and_queue_callback_task(updated_notification)

    raise VirusScanError(f"notification id {notification.id} Virus scan failed")


# Cooldown before re-attempting a scan that errored out (as opposed to found a virus) --
# long enough to not hammer a struggling antivirus service, short enough that a transient
# blip clears well within the hour check_if_messagebox_still_pending waits before alerting.
MESSAGEBOX_VIRUS_SCAN_ERROR_RETRY_DELAY = 900


@notify_celery.task(name=TaskNamesNL.MESSAGEBOX_VIRUS_SCAN_ERROR, bind=True)
def messagebox_virus_scan_error(self, notification_id: str):
    """The antivirus scan itself errored (e.g. clamd unreachable) after
    scan_messagebox_attachments exhausted its own retries -- this is a
    transient infra issue, not a virus verdict, so it must be retried later
    rather than treated as a permanent failure (that's messagebox_virus_scan_
    failed, for an actual virus match, which is final and never delivered).

    Leaves the attachments in the scan bucket (a rescan needs them there) and
    the notification in pending-virus-check, and reschedules the scan. There
    is deliberately no bounded retry count/give-up-to-technical-failure here:
    dao_messagebox_notifications_still_pending's pending-virus-check branch
    already alerts Zendesk once this has been unresolved for over an hour,
    regardless of how many rescans have been scheduled underneath -- that's
    the intended circuit breaker (human investigates/decides), not an
    automatic permanent failure."""
    sentry_sdk.set_tag("notification_id", notification_id)
    current_app.logger.info("[%s] [%s]", self.name, notification_id, extra={"notification_id": notification_id})
    notification: Notification = notifications_dao.get_notification_by_id(notification_id, _raise=True)

    if notification.status != NOTIFICATION_PENDING_VIRUS_CHECK:
        current_app.logger.info(
            "[%s] [%s] notification already in status %s, not rescheduling scan",
            self.name,
            notification_id,
            notification.status,
            extra={"notification_id": notification_id},
        )
        return

    current_app.logger.warning(
        "[%s] [%s] virus scan errored, rescheduling scan in %ss",
        self.name,
        notification_id,
        MESSAGEBOX_VIRUS_SCAN_ERROR_RETRY_DELAY,
        extra={"notification_id": notification_id},
    )

    notify_celery.send_task(
        name=TaskNamesNL.MESSAGEBOX_SCAN_ATTACHMENTS,
        kwargs={"notification_id": str(notification.id)},
        queue=QueueNames.ANTIVIRUS,
        countdown=MESSAGEBOX_VIRUS_SCAN_ERROR_RETRY_DELAY,
    )


@notify_celery.task(name=TaskNamesNL.MESSAGEBOX_VIRUS_SCAN_SUCCESS, bind=True)
def messagebox_virus_scan_success(self, notification_id: str):
    sentry_sdk.set_tag("notification_id", notification_id)
    current_app.logger.info("[%s] [%s]", self.name, notification_id, extra={"notification_id": notification_id})
    notification: Notification = notifications_dao.get_notification_by_id(notification_id, _raise=True)

    if notification.status != NOTIFICATION_PENDING_VIRUS_CHECK:
        # Mirrors messagebox_virus_scan_error's guard above - a stale/duplicate trigger
        # for a notification that already moved past pending-virus-check (e.g. a
        # test-key send, which is persisted already-delivered) must be a safe no-op,
        # not a re-delivery.
        current_app.logger.info(
            "[%s] [%s] notification already in status %s, not delivering",
            self.name,
            notification_id,
            notification.status,
            extra={"notification_id": notification_id},
        )
        return

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
    sentry_sdk.set_tag("notification_id", notification_id)
    current_app.logger.info("[%s] [%s]", self.name, notification_id, extra={"notification_id": notification_id})
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
            extra={"notification_id": notification_id},
        )
        return

    try:
        envelope_message_id = ebms_adapter_client.send_messagebox(str(notification.id))
    except MessageboxClientNonRetryableException as e:
        current_app.logger.exception(
            "Messagebox notification %s failed: %s", notification_id, e, extra={"notification_id": notification_id}
        )
        notifications_dao.update_notification_status_by_id(notification.id, NOTIFICATION_TECHNICAL_FAILURE)
        return
    except Exception:
        current_app.logger.exception(
            "RETRY: Messagebox notification %s failed", notification_id, extra={"notification_id": notification_id}
        )
        # Touch updated_at so dao_messagebox_notifications_still_pending can tell an
        # actively-retrying notification apart from one whose dispatch was genuinely
        # lost -- status stays NOTIFICATION_CREATED throughout retries, so created_at
        # alone can't distinguish the two.
        notifications_dao.dao_update_notification(notification)
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
