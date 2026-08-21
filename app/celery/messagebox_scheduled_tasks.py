import logging
from datetime import datetime, timedelta

from ebms_adapter_client import EbmsAdapterClientConfig
from ebms_adapter_client.berichtenbox import parse_berichten_verwerk_response
from ebms_adapter_client.client import EbmsAdapterClient as EbmsCoreClient
from flask import current_app
from notifications_utils.clients.zendesk.zendesk_client import NotifySupportTicket, NotifyTicketType

from app import notify_celery, statsd_client, zendesk_client
from app.celery.process_messagebox_client_response_tasks import process_messagebox_client_response
from app.config import QueueNamesNL, TaskNamesNL
from app.constants import NOTIFICATION_CREATED, NOTIFICATION_PENDING_VIRUS_CHECK
from app.dao.notifications_dao import (
    dao_messagebox_notifications_still_pending,
    dao_messagebox_notifications_stuck_sending,
)

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
                statsd_client.incr("messagebox.envelope-fetch-parse-failure")
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

        if current_app.should_send_zendesk_alerts:
            environment = current_app.config["NOTIFY_ENVIRONMENT"]
            ticket = NotifySupportTicket(
                subject=f"[{environment}] Messagebox notifications still pending virus check",
                message=msg,
                ticket_type=NotifySupportTicket.TYPE_TASK,
                notify_ticket_type=NotifyTicketType.TECHNICAL,
                notify_task_type="notify_task_messagebox_pending_scan",
            )
            zendesk_client.send_ticket_to_zendesk(ticket)
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

        if current_app.should_send_zendesk_alerts:
            environment = current_app.config["NOTIFY_ENVIRONMENT"]
            ticket = NotifySupportTicket(
                subject=f"[{environment}] Messagebox notifications stuck sending",
                message=msg,
                ticket_type=NotifySupportTicket.TYPE_TASK,
                notify_ticket_type=NotifyTicketType.TECHNICAL,
                notify_task_type="notify_task_messagebox_stuck_sending",
            )
            zendesk_client.send_ticket_to_zendesk(ticket)
            current_app.logger.error(
                "Messagebox notifications stuck sending",
                extra={"number_of_notifications": len(stuck_sending), "notification_ids": notification_ids},
            )
