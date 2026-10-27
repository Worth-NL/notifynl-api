from collections import Counter
from datetime import datetime, timedelta

from botocore.exceptions import ClientError as BotoClientError
from celery.exceptions import Retry
from flask import current_app
from notifications_utils.clients.zendesk.zendesk_client import NotifySupportTicket, NotifyTicketType
from notifications_utils.timezones import convert_utc_to_bst
from redis.exceptions import RedisError

from app import db, notify_celery, redis_store, signing, zendesk_client
from app.clients.letter import (
    Letter,
    LetterClientNonRetryableException,
    LetterClientRetryableException,
)
from app.config import QueueNames, TaskNamesNL
from app.constants import (
    KEY_TYPE_NORMAL,
    LETTER_TYPE,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_RETURNED_LETTER,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_TECHNICAL_FAILURE,
)
from app.dao.letter_provider_reference_dao import (
    dao_create_letter_provider_reference,
    dao_get_letter_provider_reference,
)
from app.dao.notifications_dao import (
    dao_claim_letter_for_sending,
    dao_get_letters_ready_to_send_since,
    dao_get_letters_stuck_sending,
    dao_get_notification_or_history_by_id,
    dao_letters_in_technical_failure,
    dao_mark_letter_sent,
    dao_record_letter_despatched_on_by_id,
    dao_touch_notification,
    dao_update_letter_status_from_provider,
    get_notification_by_id,
    update_notification_status_by_id,
)
from app.letters.utils import LetterPDFNotFound, find_letter_pdf_in_s3
from app.letters_nl.constants import LETTER_PROVIDER_CALLBACK_PATH
from app.letters_nl.provider import resolve_letter_provider
from app.models import LetterCostThreshold
from app.notifications.notifications_ses_callback import check_and_queue_callback_task

# 55 retries 3 minutes apart: a print provider can be unavailable for up to ~2h45m before a letter fails
DELIVERY_MAX_RETRIES = 55
DELIVERY_RETRY_DELAY = 180
# the delivery lock outlives a slow provider call, so a duplicate message can't start a second one meanwhile
DELIVERY_LOCK_TIMEOUT = 600
# letters ready to send for this long without being picked up (e.g. a lost message) are queued by the sweep
STRANDED_AFTER = timedelta(minutes=15)
# longer than all delivery retries together
STUCK_SENDING_AFTER = timedelta(hours=4)


def queue_letter_for_delivery(notification):
    """
    Hand a letter to its print provider as soon as its PDF is ready. Called wherever a letter becomes ready to send;
    a no-op unless LETTER_DELIVERY_VIA_PROVIDERS is on, in which case the DVLA collation no longer runs.
    """
    if not current_app.config.get("LETTER_DELIVERY_VIA_PROVIDERS"):
        return
    if notification.notification_type != LETTER_TYPE or notification.key_type != KEY_TYPE_NORMAL:
        return
    deliver_letter_via_provider.apply_async(
        [str(notification.id)], queue=QueueNames.SEND_LETTER, MessageGroupId=str(notification.service_id)
    )


@notify_celery.task(
    bind=True,
    name=TaskNamesNL.DELIVER_LETTER_VIA_PROVIDER,
    max_retries=DELIVERY_MAX_RETRIES,
    default_retry_delay=DELIVERY_RETRY_DELAY,
)
def deliver_letter_via_provider(self, notification_id):
    notification = get_notification_by_id(notification_id)
    extra = {"notification_id": notification_id}
    if not notification or notification.key_type != KEY_TYPE_NORMAL:
        current_app.logger.warning(
            "Not delivering letter %s: no live letter with this id", notification_id, extra=extra
        )
        return

    if not dao_claim_letter_for_sending(notification_id):
        # only the delivery attempt that claimed the letter continues, on its own retries
        if not (notification.status == NOTIFICATION_SENDING and self.request.retries > 0):
            current_app.logger.info(
                "Not delivering letter %s: already %s", notification_id, notification.status, extra=extra
            )
            return

    lock = redis_store.get_lock(f"deliver-letter-{notification_id}", timeout=DELIVERY_LOCK_TIMEOUT, blocking=False)
    try:
        acquired = lock.acquire()
    except RedisError:
        # the letter is already claimed, so without a retry nothing would pick it up again
        current_app.logger.exception("RETRY: could not lock letter %s for delivery", notification_id, extra=extra)
        _retry(self, notification_id, "print-provider-error")
        return
    if not acquired:
        current_app.logger.info("Not delivering letter %s: already being delivered", notification_id, extra=extra)
        return
    try:
        # while this attempt waited for the lock, a duplicate message may have delivered the letter
        db.session.refresh(notification)
        if notification.status != NOTIFICATION_SENDING:
            current_app.logger.info(
                "Not delivering letter %s: already %s", notification_id, notification.status, extra=extra
            )
            return
        _deliver_claimed_letter(self, notification)
    except Retry:
        raise
    except Exception:
        # retrying is safe: the letter stays claimed, and retried sends are idempotent where providers support it
        current_app.logger.exception("RETRY: delivering letter %s failed unexpectedly", notification_id, extra=extra)
        db.session.rollback()
        _retry(self, notification_id, "print-provider-error")
    finally:
        _release(lock, notification_id)


def _release(lock, notification_id):
    # the lock expires by itself, so failing to release it (Redis down, or already expired) mustn't change the outcome
    try:
        lock.release()
    except RedisError:
        current_app.logger.warning(
            "Could not release the delivery lock of letter %s",
            notification_id,
            exc_info=True,
            extra={"notification_id": notification_id},
        )


def _deliver_claimed_letter(task, notification):
    notification_id = str(notification.id)
    service = notification.service

    if service.organisation_id is None:
        # services without an organisation can't go live, so can't send real letters
        _fail(notification_id, "no-organisation")
        return

    if reference := dao_get_letter_provider_reference(notification_id):
        # an earlier attempt got the letter accepted but didn't get to mark it sent
        _mark_sent(notification_id, reference.provider)
        return

    client, letter_provider = resolve_letter_provider(service.organisation_id)

    try:
        pdf = find_letter_pdf_in_s3(notification).get()["Body"].read()
    except (BotoClientError, LetterPDFNotFound):
        current_app.logger.warning(
            "PDF for letter %s not found (yet)", notification_id, extra={"notification_id": notification_id}
        )
        _retry(task, notification_id, "letter-pdf-not-found")
        return

    letter = Letter(
        notification_id=notification_id,
        reference=_reference_for_provider(notification),
        organisation_id=str(service.organisation_id),
        pdf=pdf,
        postage=notification.postage,
        callback_url=_callback_url(notification_id),
    )

    try:
        result = client.send_letter(letter, letter_provider)
    except LetterClientRetryableException:
        current_app.logger.exception(
            "RETRY: letter %s could not be sent with %s",
            notification_id,
            client.name,
            extra={"notification_id": notification_id, "provider_name": client.name},
        )
        _retry(task, notification_id, "print-provider-unavailable")
        return
    except LetterClientNonRetryableException as e:
        current_app.logger.exception(
            "Letter %s was rejected by %s",
            notification_id,
            client.name,
            extra={"notification_id": notification_id, "provider_name": client.name},
        )
        _fail(notification_id, e.detailed_status_code)
        return

    if result.provider_reference:
        dao_create_letter_provider_reference(notification_id, client.name, result.provider_reference)
    _mark_sent(notification_id, client.name)


def _reference_for_provider(notification):
    if notification.service.send_client_reference_to_letter_provider:
        if notification.client_reference:
            return notification.client_reference
        current_app.logger.info(
            "Letter %s has no client reference, sending its generated reference instead",
            notification.id,
            extra={"notification_id": notification.id},
        )
    return notification.reference


def _callback_url(notification_id):
    return (
        f"{current_app.config['API_HOST_NAME']}{LETTER_PROVIDER_CALLBACK_PATH}?token={signing.encode(notification_id)}"
    )


def _mark_sent(notification_id, sent_by):
    if dao_mark_letter_sent(notification_id, sent_by):
        check_and_queue_callback_task(get_notification_by_id(notification_id, _raise=True))


def _fail(notification_id, detailed_status_code):
    notification = update_notification_status_by_id(
        notification_id, NOTIFICATION_TECHNICAL_FAILURE, detailed_status_code=detailed_status_code
    )
    if notification:
        check_and_queue_callback_task(notification)


def _retry(task, notification_id, detailed_status_code):
    dao_touch_notification(notification_id)
    try:
        task.retry()
    except task.MaxRetriesExceededError:
        current_app.logger.error(
            "RETRY FAILED: letter %s could not be delivered, marking it as technical-failure",
            notification_id,
            extra={"notification_id": notification_id},
        )
        _fail(notification_id, detailed_status_code)


@notify_celery.task(name=TaskNamesNL.DISPATCH_STRANDED_LETTERS)
def dispatch_stranded_letters():
    """Safety net for letters that are ready to send but whose delivery was never queued (or was lost)."""
    if not current_app.config.get("LETTER_DELIVERY_VIA_PROVIDERS"):
        return
    notification_ids = dao_get_letters_ready_to_send_since(datetime.utcnow() - STRANDED_AFTER)
    for notification_id in notification_ids:
        deliver_letter_via_provider.apply_async([str(notification_id)], queue=QueueNames.SEND_LETTER)
    if notification_ids:
        current_app.logger.warning(
            "Queued %s stranded letters for delivery",
            len(notification_ids),
            extra={"number_of_notifications": len(notification_ids)},
        )


@notify_celery.task(name=TaskNamesNL.CHECK_LETTERS_STUCK_SENDING)
def check_letters_stuck_sending():
    """Letters stay `sending` while their delivery is retried; longer than all retries means something is wrong."""
    stuck = dao_get_letters_stuck_sending(datetime.utcnow() - STUCK_SENDING_AFTER)
    if not stuck:
        return

    notification_ids = sorted(str(notification.id) for notification in stuck)
    current_app.logger.error(
        "Letters stuck sending to their print provider",
        extra={"number_of_notifications": len(notification_ids), "notification_ids": notification_ids},
    )
    if current_app.should_send_zendesk_alerts:
        environment = current_app.config["NOTIFY_ENVIRONMENT"]
        zendesk_client.send_ticket_to_zendesk(
            NotifySupportTicket(
                subject=f"[{environment}] Letters stuck sending to their print provider",
                message=(
                    f"{len(notification_ids)} letters have been sending for over {STUCK_SENDING_AFTER} without being "
                    "accepted by their print provider or failing. Check whether they were accepted (e.g. in Pingen) "
                    "before resending.\n\n"
                    f"Notifications: {notification_ids}"
                ),
                ticket_type=NotifySupportTicket.TYPE_TASK,
                notify_ticket_type=NotifyTicketType.TECHNICAL,
                notify_task_type="notify_task_letters_stuck_sending",
            )
        )


@notify_celery.task(name=TaskNamesNL.CHECK_PROVIDER_LETTERS_IN_TECHNICAL_FAILURE)
def check_provider_letters_in_technical_failure():
    """
    Letters that failed on our side or their print provider's in the last 3 days: rejected (e.g. a misconfigured
    provider), out of retries, or with issues reported by the provider. Replaces upstream's check, which points at the
    DVLA runbook.
    """
    letters = dao_letters_in_technical_failure(session=db.session_bulk, retry_attempts=2)
    if not letters:
        return

    notification_ids = sorted(str(notification.id) for notification in letters)
    status_codes = Counter(notification.detailed_status_code or "unknown" for notification in letters)
    current_app.logger.error(
        "Letters in technical-failure",
        extra={
            "number_of_notifications": len(notification_ids),
            "notification_ids": notification_ids,
            "detailed_status_codes": dict(status_codes),
        },
    )
    if current_app.should_send_zendesk_alerts:
        environment = current_app.config["NOTIFY_ENVIRONMENT"]
        zendesk_client.send_ticket_to_zendesk(
            NotifySupportTicket(
                subject=f"[{environment}] Letters in 'technical-failure' status",
                message=(
                    f"{len(notification_ids)} letters created in the last 3 days have 'technical-failure' status. "
                    "The detailed status code says why (e.g. pingen-http-404 or endpoint-http-400 for a rejected "
                    "letter, print-provider-unavailable after running out of retries, print-provider-issue when the "
                    "provider reported a problem). Check the organisation's letter provider before resending.\n\n"
                    f"Detailed status codes: {dict(sorted(status_codes.items()))}\n\n"
                    f"Notifications: {notification_ids}"
                ),
                ticket_type=NotifySupportTicket.TYPE_TASK,
                notify_ticket_type=NotifyTicketType.TECHNICAL,
                notify_task_type="notify_task_letters_technical_failure_status",
            )
        )


# the statuses a print provider's report may move a letter from: never backwards, and never twice
PROVIDER_STATUS_TRANSITIONS = {
    NOTIFICATION_DELIVERED: {NOTIFICATION_SENDING, NOTIFICATION_SENT},
    NOTIFICATION_PERMANENT_FAILURE: {NOTIFICATION_SENDING, NOTIFICATION_SENT},
    NOTIFICATION_TECHNICAL_FAILURE: {NOTIFICATION_SENDING, NOTIFICATION_SENT},
    # a letter can come back after it was handed to the postal service
    NOTIFICATION_RETURNED_LETTER: {NOTIFICATION_SENDING, NOTIFICATION_SENT, NOTIFICATION_DELIVERED},
}
PROVIDER_DETAILED_STATUS_CODES = {
    NOTIFICATION_PERMANENT_FAILURE: "print-provider-rejected",
    NOTIFICATION_TECHNICAL_FAILURE: "print-provider-issue",
}


@notify_celery.task(name=TaskNamesNL.PROCESS_LETTER_PROVIDER_STATUS)
def process_letter_provider_status(notification_id, provider, status, reason=None, receipt_iso_timestamp=None):
    """A print provider reported back on a letter it accepted (REST endpoint callback or Pingen webhook)."""
    receipt_dt = None
    if receipt_iso_timestamp is not None:
        try:
            receipt_dt = datetime.fromisoformat(receipt_iso_timestamp)
        except ValueError:
            pass  # None it is, then

    # providers can report back after the letter moved to notification_history
    notification = dao_get_notification_or_history_by_id(notification_id)
    if not notification:
        current_app.logger.warning(
            "Ignoring %s status %s for unknown letter %s",
            provider,
            status,
            notification_id,
            extra={"notification_id": notification_id, "provider_name": provider, "notification_status_new": status},
        )
        return

    extra = {
        "notification_id": notification_id,
        "provider_name": provider,
        "notification_status": notification.status,
        "notification_status_new": status,
        "reason": reason,
    }
    # checked as part of the update: another report for this letter can be processed at the same time
    if not dao_update_letter_status_from_provider(
        notification_id,
        status,
        PROVIDER_STATUS_TRANSITIONS[status],
        provider,
        detailed_status_code=PROVIDER_DETAILED_STATUS_CODES.get(status),
    ):
        current_app.logger.info(
            "Ignoring %s status %s for letter %s, which is %s",
            provider,
            status,
            notification_id,
            notification.status,
            extra=extra,
        )
        return

    current_app.logger.info("Letter %s is %s according to %s", notification_id, status, provider, extra=extra)

    if status == NOTIFICATION_RETURNED_LETTER:
        from app.celery.tasks import process_returned_letters_list

        # also records the returned letter for the service's report and sends the returned letter callback
        process_returned_letters_list([notification.reference])
        return

    db.session.refresh(notification)
    if status == NOTIFICATION_DELIVERED:
        dao_record_letter_despatched_on_by_id(
            notification.id, convert_utc_to_bst(datetime.utcnow()).date(), LetterCostThreshold.unsorted
        )
    check_and_queue_callback_task(notification, receipt_dt=receipt_dt)
