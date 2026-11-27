import logging
from collections import Counter
from datetime import datetime, timedelta

from ebms_adapter_client import EbmsAdapterClientConfig, EbmsAdapterError, EbMSMessageStatus, EbmsNotFoundError
from ebms_adapter_client.berichtenbox import parse_berichten_verwerk_response
from ebms_adapter_client.client import EbmsAdapterClient as EbmsCoreClient
from flask import current_app
from notifications_utils.clients.zendesk.zendesk_client import NotifySupportTicket, NotifyTicketType

from app import notify_celery, zendesk_client
from app.celery.process_messagebox_client_response_tasks import process_messagebox_client_response
from app.config import QueueNamesNL, TaskNamesNL
from app.constants import (
    KEY_TYPE_TEAM,
    NOTIFICATION_CREATED,
    NOTIFICATION_PENDING_VIRUS_CHECK,
    NOTIFICATION_TECHNICAL_FAILURE,
)
from app.dao import notifications_dao
from app.dao.messagebox_notifications_dao_nl import (
    dao_messagebox_notifications_sending_to_check,
    dao_messagebox_notifications_technical_failure_between,
)
from app.dao.notifications_dao import (
    dao_messagebox_notifications_still_pending,
    dao_messagebox_notifications_stuck_sending,
)
from app.messagebox.constants import TECHNICAL_FAILURE_EBMS_DELIVERY_FAILED, TECHNICAL_FAILURE_EBMS_EXPIRED
from app.notifications.notifications_ses_callback import check_and_queue_callback_task
from app.otel_metrics.messagebox_nl import record_envelope_fetch_parse_failure

MESSAGEBOX_STATUS_DELIVERED = "10"
MESSAGEBOX_STATUS_FAILED = "20"

# Logius echoes this literal nil UUID as BerichtID when it can't extract our real
# notification id from the submitted message (e.g. XSD validation failure, or
# VerwerkingsCode=OinInCPAKomtNietOvereenMetOinInBericht) -- BatchID (which
# app/clients/messagebox/ebms_adapter.py sets to the notification id itself, and which
# Logius always echoes back verbatim regardless of BerichtID) is the fallback correlation
# key in that case.
MESSAGEBOX_NIL_BERICHT_ID = "00000000-0000-0000-0000-000000000000"


@notify_celery.task(name=TaskNamesNL.MESSAGEBOX_PROCESS_UNPROCESSED, early_log_level=logging.DEBUG)
def messagebox_process_unprocessed_messages():
    """Polls the ebms-adapter for unprocessed envelope messages, parses each
    envelope's BerichtVerwerkResponse content, and dispatches
    process_messagebox_client_response per contained Bericht (matched by
    BerichtID == notification.id, falling back to BatchID when Logius echoes
    back a nil BerichtID -- see MESSAGEBOX_NIL_BERICHT_ID). Marks each
    envelope processed only after all its messages have been successfully
    enqueued -- at-least-once, safe
    to re-poll on partial failure."""
    config = EbmsAdapterClientConfig(base_url=current_app.config["EBMS_ADAPTER_URL"])
    with EbmsCoreClient(config) as core_client:
        envelope_ids = core_client.list_unprocessed_message_ids()
        current_app.logger.info("Messagebox poll found %s unprocessed envelope(s)", len(envelope_ids))

        for envelope_id in envelope_ids:
            try:
                message = core_client.get_message(envelope_id)
                batch = parse_berichten_verwerk_response(message.data_sources[0].content)
            except Exception as e:
                record_envelope_fetch_parse_failure()
                current_app.logger.exception(
                    "Failed to fetch/parse messagebox envelope %s, will retry next poll",
                    envelope_id,
                    extra={"envelope_id": envelope_id, "exception_type": type(e).__name__},
                )
                continue

            status = MESSAGEBOX_STATUS_DELIVERED if batch.batch_success else MESSAGEBOX_STATUS_FAILED

            all_dispatched = True
            for bericht in batch.messages:
                resolved_message_id = (
                    batch.batch_id if bericht.message_id == MESSAGEBOX_NIL_BERICHT_ID else bericht.message_id
                )
                if resolved_message_id != bericht.message_id:
                    current_app.logger.info(
                        "Messagebox message in envelope %s has nil BerichtID, resolved via batch_id to %s",
                        envelope_id,
                        resolved_message_id,
                        extra={"envelope_id": envelope_id, "resolved_message_id": resolved_message_id},
                    )
                try:
                    process_messagebox_client_response.apply_async(
                        [
                            status,
                            resolved_message_id,
                            "ebms-adapter",
                            bericht.process_code,
                            bericht.stadium,
                            envelope_id,
                        ],
                        queue=QueueNamesNL.MESSAGEBOX_CALLBACKS,
                    )
                except Exception:
                    current_app.logger.exception(
                        "Failed to queue status update for messagebox message %s in envelope %s",
                        resolved_message_id,
                        envelope_id,
                    )
                    all_dispatched = False

            acked = False
            if all_dispatched:
                try:
                    core_client.process_message(envelope_id)
                    acked = True
                except Exception:
                    current_app.logger.exception(
                        "Failed to mark messagebox envelope %s processed, will retry next poll", envelope_id
                    )

            current_app.logger.info(
                "Messagebox envelope %s poll cycle complete: %d message(s), batch_status=%s, "
                "all_dispatched=%s, acked=%s",
                envelope_id,
                len(batch.messages),
                status,
                all_dispatched,
                acked,
                extra={
                    "envelope_id": envelope_id,
                    "message_ids": [bericht.message_id for bericht in batch.messages],
                    "batch_status": status,
                    "all_dispatched": all_dispatched,
                    "acked": acked,
                },
            )


@notify_celery.task(name=TaskNamesNL.MESSAGEBOX_CHECK_STILL_PENDING)
def check_if_messagebox_still_pending(max_minutes_ago_to_check: int = 60, max_hours_ago_to_check_sending: int = 24):
    """Finds messagebox notifications stuck in pending-virus-check or created
    for longer than max_minutes_ago_to_check. `created` is re-dispatched to
    messagebox_deliver (e.g. the trigger was lost). pending-virus-check only
    alerts, it never re-triggers a scan itself -- a scan that errored out is
    already being retried by messagebox_virus_scan_error (see
    app/celery/messagebox_tasks.py), so a notification that's still stuck
    here despite that has no other automatic recovery path (e.g. the initial
    scan dispatch itself was lost) and needs a human to look.

    Separately, alerts (never resends) on notifications stuck `sending` for
    longer than max_hours_ago_to_check_sending: `sending` means ebms-core
    already accepted the message and we're only waiting on its async result,
    which has no fixed SLA -- blindly resending would duplicate the outbound
    call and race the real result (ebms-core rejects the duplicate as
    BerichtBestaatAl), so a stuck one always needs human investigation into
    whether messagebox_process_unprocessed_messages has stopped draining the
    unprocessed envelope queue."""
    cutoff_time = datetime.utcnow() - timedelta(minutes=max_minutes_ago_to_check)
    notifications = dao_messagebox_notifications_still_pending(cutoff_time)

    stuck_pending_virus_check = []
    for notification in notifications:
        if notification.status == NOTIFICATION_CREATED:
            current_app.logger.warning(
                "Messagebox notification %s stuck in %s. Re-dispatching messagebox_deliver.",
                notification.id,
                notification.status,
            )
            notify_celery.send_task(
                name=TaskNamesNL.MESSAGEBOX_DELIVER,
                kwargs={"notification_id": str(notification.id)},
                queue=QueueNamesNL.MESSAGEBOX,
            )
        elif notification.status == NOTIFICATION_PENDING_VIRUS_CHECK:
            stuck_pending_virus_check.append(notification)

    if stuck_pending_virus_check:
        notification_ids = sorted(str(notification.id) for notification in stuck_pending_virus_check)

        msg = (
            f"{len(stuck_pending_virus_check)} messagebox notifications have been pending-virus-check for over "
            f"{max_minutes_ago_to_check} minutes. This needs manual investigation.\n\n"
            f"Notifications: {notification_ids}"
        )

        if current_app.should_send_zendesk_alerts:  # type: ignore[attr-defined]
            environment = current_app.config["NOTIFY_ENVIRONMENT"]
            ticket = NotifySupportTicket(
                subject=f"[{environment}] Messagebox notifications still pending virus check",
                message=msg,
                ticket_type=NotifySupportTicket.TYPE_TASK,
                notify_ticket_type=NotifyTicketType.TECHNICAL,
                notify_task_type="notify_task_messagebox_pending_scan",
            )
            zendesk_client.send_ticket_to_zendesk(ticket)  # type: ignore[attr-defined]
            current_app.logger.error(
                "Messagebox notifications still pending virus check",
                extra={"number_of_notifications": len(stuck_pending_virus_check), "notification_ids": notification_ids},
            )

    sending_cutoff_time = datetime.utcnow() - timedelta(hours=max_hours_ago_to_check_sending)
    stuck_sending = dao_messagebox_notifications_stuck_sending(sending_cutoff_time)

    if stuck_sending:
        notification_ids = sorted(str(notification.id) for notification in stuck_sending)

        msg = (
            f"{len(stuck_sending)} messagebox notifications have been sending for over "
            f"{max_hours_ago_to_check_sending} hours with no result from ebms-core. This likely means "
            "messagebox_process_unprocessed_messages has stopped draining the unprocessed envelope queue -- "
            "needs manual investigation. Do not resend.\n\n"
            f"Notifications: {notification_ids}"
        )
        # Team-key notifications went to Logius pre-production (app/messagebox/contract_nl.py), which may be down
        # or slow on its own without anything being wrong with production.
        team_key_ids = sorted(
            str(notification.id) for notification in stuck_sending if notification.key_type == KEY_TYPE_TEAM
        )
        if team_key_ids:
            msg += f"\n\nOf these, sent with a team key to Logius pre-production: {team_key_ids}"

        if current_app.should_send_zendesk_alerts:  # type: ignore[attr-defined]
            environment = current_app.config["NOTIFY_ENVIRONMENT"]
            ticket = NotifySupportTicket(
                subject=f"[{environment}] Messagebox notifications stuck sending",
                message=msg,
                ticket_type=NotifySupportTicket.TYPE_TASK,
                notify_ticket_type=NotifyTicketType.TECHNICAL,
                notify_task_type="notify_task_messagebox_stuck_sending",
            )
            zendesk_client.send_ticket_to_zendesk(ticket)  # type: ignore[attr-defined]
            current_app.logger.error(
                "Messagebox notifications stuck sending",
                extra={"number_of_notifications": len(stuck_sending), "notification_ids": notification_ids},
            )


# A broken CPA or ebms-adapter fails every message, so the ticket and log line name a sample, not all of them.
MESSAGEBOX_TECHNICAL_FAILURE_ALERT_MAX_IDS = 50


def _sample_ids(ids):
    sample = sorted(ids)[:MESSAGEBOX_TECHNICAL_FAILURE_ALERT_MAX_IDS]
    if len(ids) > len(sample):
        return f"{sample} (first {len(sample)} of {len(ids)})"
    return f"{sample}"


@notify_celery.task(name=TaskNamesNL.MESSAGEBOX_ALERT_TECHNICAL_FAILURES)
def messagebox_alert_technical_failures():
    """One Zendesk ticket for the messagebox notifications that moved to
    technical-failure in the previous whole hour. The service falls back to
    another channel (e.g. a letter), so the citizen still gets the message, but
    the cause is on our side or in the delivery chain (a bug, the CPA, the
    ebms-adapter) and needs looking into. One ticket per hour rather than per
    notification, since a bug fails every message.

    Runs on the hour (its own beat entry), and the window ends at the start of
    the current hour, so every failure falls in exactly one window."""
    end = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=1)
    failed = dao_messagebox_notifications_technical_failure_between(start, end)
    if not failed:
        return

    notification_ids = [str(notification.id) for notification in failed]
    counts_by_code = Counter(notification.detailed_status_code or "unknown" for notification in failed)

    msg = (
        f"{len(failed)} messagebox notifications moved to technical-failure between {start:%Y-%m-%d %H:%M} and "
        f"{end:%H:%M} UTC. Services with a delivery-status callback were told, so they can fall back to another "
        "channel. This needs investigation: it points at a bug or a misconfiguration (CPA, ebms-adapter).\n\n"
        f"By cause: {dict(sorted(counts_by_code.items()))}\n"
        "messagebox-send-* and ebms-* never reached Logius. 'unknown' means Logius answered with a status Notify "
        "doesn't recognise.\n\n"
        f"Notifications: {_sample_ids(notification_ids)}"
    )
    # Team-key notifications went to Logius pre-production (app/messagebox/contract_nl.py): no citizen is affected.
    team_key_ids = [str(notification.id) for notification in failed if notification.key_type == KEY_TYPE_TEAM]
    if team_key_ids:
        msg += f"\n\nOf these, sent with a team key to Logius pre-production: {_sample_ids(team_key_ids)}"

    current_app.logger.error(
        "Messagebox notifications in technical-failure",
        extra={
            "number_of_notifications": len(failed),
            "notification_ids": sorted(notification_ids)[:MESSAGEBOX_TECHNICAL_FAILURE_ALERT_MAX_IDS],
            "detailed_status_codes": dict(counts_by_code),
        },
    )

    if current_app.should_send_zendesk_alerts:  # type: ignore[attr-defined]
        environment = current_app.config["NOTIFY_ENVIRONMENT"]
        ticket = NotifySupportTicket(
            subject=f"[{environment}] Messagebox notifications in technical-failure",
            message=msg,
            ticket_type=NotifySupportTicket.TYPE_TASK,
            notify_ticket_type=NotifyTicketType.TECHNICAL,
            notify_task_type="notify_task_messagebox_technical_failure",
        )
        zendesk_client.send_ticket_to_zendesk(ticket)  # type: ignore[attr-defined]


# ebms-core statuses of our own outgoing message that mean it will never reach Logius: the counterparty rejected it
# at ebMS level (e.g. an unknown CPAId), or ebms-core gave up retrying before its TimeToLive. Logius then never sends
# a BerichtVerwerkResponse, so messagebox_process_unprocessed_messages can't settle the notification.
EBMS_DELIVERY_FAILURE_STATUS_CODES = {
    EbMSMessageStatus.DELIVERY_FAILED: TECHNICAL_FAILURE_EBMS_DELIVERY_FAILED,
    EbMSMessageStatus.EXPIRED: TECHNICAL_FAILURE_EBMS_EXPIRED,
}
# Still being delivered by ebms-core, or accepted at ebMS level and waiting for Logius' async BerichtVerwerkResponse.
EBMS_IN_PROGRESS_STATUSES = {EbMSMessageStatus.CREATED, EbMSMessageStatus.DELIVERED}

MESSAGEBOX_CHECK_SENDING_STATUS_MIN_AGE = timedelta(minutes=5)
MESSAGEBOX_CHECK_SENDING_STATUS_MAX_AGE = timedelta(days=7)
MESSAGEBOX_CHECK_SENDING_STATUS_BATCH_SIZE = 500


@notify_celery.task(name=TaskNamesNL.MESSAGEBOX_CHECK_SENDING_STATUS, early_log_level=logging.DEBUG)
def messagebox_check_sending_status():
    """Asks ebms-core for the delivery status of each messagebox notification
    still in `sending`, and moves the ones ebms-core couldn't deliver to
    technical-failure, with a service callback.

    Without this, an ebMS-level rejection leaves the notification in `sending`
    forever: the only other way out is Logius' async BerichtVerwerkResponse
    (messagebox_process_unprocessed_messages), which never comes for a message
    Logius didn't accept. technical-failure rather than permanent-failure: the
    cause is the delivery chain (CPA, certificate, endpoint), not the
    recipient, so the service may send it again once that's fixed."""
    now = datetime.utcnow()
    notifications = dao_messagebox_notifications_sending_to_check(
        older_than=now - MESSAGEBOX_CHECK_SENDING_STATUS_MIN_AGE,
        newer_than=now - MESSAGEBOX_CHECK_SENDING_STATUS_MAX_AGE,
        limit=MESSAGEBOX_CHECK_SENDING_STATUS_BATCH_SIZE,
    )
    if not notifications:
        return

    config = EbmsAdapterClientConfig(base_url=current_app.config["EBMS_ADAPTER_URL"])
    failed = 0
    with EbmsCoreClient(config) as core_client:
        for notification in notifications:
            extra = {"notification_id": str(notification.id), "ebms_message_id": notification.reference}
            try:
                ebms_status = core_client.get_message_status(notification.reference).status
            except EbmsNotFoundError:
                current_app.logger.warning(
                    "ebms-core doesn't know message %s of messagebox notification %s",
                    notification.reference,
                    notification.id,
                    extra=extra,
                )
                continue
            except EbmsAdapterError:
                # ebms-core unreachable or failing: stop here instead of hammering it, the next run tries again.
                current_app.logger.exception(
                    "Couldn't get the ebms-core status of messagebox notification %s, will retry next run",
                    notification.id,
                    extra=extra,
                )
                break

            if ebms_status in EBMS_IN_PROGRESS_STATUSES:
                continue

            detailed_status_code = EBMS_DELIVERY_FAILURE_STATUS_CODES.get(ebms_status)
            if detailed_status_code is None:
                current_app.logger.warning(
                    "Unexpected ebms-core status %s for messagebox notification %s, leaving it in sending",
                    ebms_status,
                    notification.id,
                    extra={**extra, "ebms_status": ebms_status},
                )
                continue

            # update_notification_status_by_id only moves a notification that's still in a pre-callback status, so a
            # result processed by messagebox_process_unprocessed_messages in the meantime is never overwritten.
            updated = notifications_dao.update_notification_status_by_id(
                notification.id, NOTIFICATION_TECHNICAL_FAILURE, detailed_status_code=detailed_status_code
            )
            if not updated:
                continue

            failed += 1
            current_app.logger.warning(
                "Messagebox notification %s not delivered by ebms-core (%s), moved to %s",
                notification.id,
                ebms_status,
                NOTIFICATION_TECHNICAL_FAILURE,
                extra={**extra, "ebms_status": ebms_status, "detailed_status_code": detailed_status_code},
            )
            check_and_queue_callback_task(updated)

    current_app.logger.info(
        "Messagebox sending status check: %s checked, %s moved to %s",
        len(notifications),
        failed,
        NOTIFICATION_TECHNICAL_FAILURE,
        extra={"number_of_notifications": len(notifications), "number_failed": failed},
    )
