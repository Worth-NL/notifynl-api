import logging
from datetime import datetime, timedelta

from ebms_adapter_client import EbmsAdapterClientConfig
from ebms_adapter_client.berichtenbox import parse_berichten_verwerk_response
from ebms_adapter_client.client import EbmsAdapterClient as EbmsCoreClient
from flask import current_app
from notifications_utils.clients.zendesk.zendesk_client import NotifySupportTicket, NotifyTicketType

from app import notify_celery, redis_store, statsd_client, zendesk_client
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

# check_if_messagebox_still_pending runs hourly and, on its own, has no memory of an
# earlier alert -- a notification that's stuck (pending-virus-check or stuck-sending)
# stays stuck across every run until a human resolves it, so without this cooldown it
# would create a brand-new Zendesk ticket every single hour, indefinitely, for the same
# notification. This caps re-alerts on any one notification to once per cooldown window
# instead, while still alerting immediately the first time a notification is seen stuck.
MESSAGEBOX_STUCK_ALERT_COOLDOWN_SECONDS = 60 * 60 * 24  # 24h
MESSAGEBOX_STUCK_PENDING_VIRUS_CHECK_ALERT_REDIS_PREFIX = "messagebox-alerted:pending-virus-check"
MESSAGEBOX_STUCK_SENDING_ALERT_REDIS_PREFIX = "messagebox-alerted:stuck-sending"


def _notification_ids_due_for_alert(notification_ids: list[str], redis_key_prefix: str) -> list[str]:
    """Filters to notification ids that haven't been alerted on (via this prefix)
    within the cooldown window -- either never alerted, or the cooldown has expired."""
    return [
        notification_id
        for notification_id in notification_ids
        if redis_store.get(f"{redis_key_prefix}:{notification_id}") is None
    ]


def _mark_notifications_alerted(notification_ids: list[str], redis_key_prefix: str) -> None:
    for notification_id in notification_ids:
        redis_store.set(f"{redis_key_prefix}:{notification_id}", "1", ex=MESSAGEBOX_STUCK_ALERT_COOLDOWN_SECONDS)


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
    BerichtBestaatAl), so a stuck one always needs human investigation. A
    stopped-draining poller is only one possible cause, not the default
    assumption -- see docs/notification-flows/messagebox.md's troubleshooting
    section for how to tell that apart from ebms-core/Logius never having
    produced a result at all.

    Both alert branches re-alert on any one notification at most once per
    MESSAGEBOX_STUCK_ALERT_COOLDOWN_SECONDS (tracked in redis, keyed by
    notification id) rather than every run -- otherwise a notification that
    stays stuck for days would generate a brand-new Zendesk ticket every
    single hour, forever."""
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
        due_notification_ids = _notification_ids_due_for_alert(
            notification_ids, MESSAGEBOX_STUCK_PENDING_VIRUS_CHECK_ALERT_REDIS_PREFIX
        )

        current_app.logger.error(
            "Messagebox notifications still pending virus check",
            extra={
                "number_of_notifications": len(stuck_pending_virus_check),
                "notification_ids": notification_ids,
                "new_or_due_for_re_alert": due_notification_ids,
            },
        )

        if due_notification_ids and current_app.should_send_zendesk_alerts:
            msg = (
                f"{len(due_notification_ids)} messagebox notifications have been pending-virus-check for over "
                f"{max_minutes_ago_to_check} minutes. This needs manual investigation. Re-alerted at most once "
                f"per {MESSAGEBOX_STUCK_ALERT_COOLDOWN_SECONDS // 3600}h per notification while still stuck.\n\n"
                f"Notifications: {due_notification_ids}"
            )
            environment = current_app.config["NOTIFY_ENVIRONMENT"]
            ticket = NotifySupportTicket(
                subject=f"[{environment}] Messagebox notifications still pending virus check",
                message=msg,
                ticket_type=NotifySupportTicket.TYPE_TASK,
                notify_ticket_type=NotifyTicketType.TECHNICAL,
                notify_task_type="notify_task_messagebox_pending_scan",
            )
            zendesk_client.send_ticket_to_zendesk(ticket)
            _mark_notifications_alerted(due_notification_ids, MESSAGEBOX_STUCK_PENDING_VIRUS_CHECK_ALERT_REDIS_PREFIX)

    sending_cutoff_time = datetime.utcnow() - timedelta(hours=max_hours_ago_to_check_sending)
    stuck_sending = dao_messagebox_notifications_stuck_sending(sending_cutoff_time)

    if stuck_sending:
        notification_ids = sorted(str(notification.id) for notification in stuck_sending)
        due_notification_ids = _notification_ids_due_for_alert(
            notification_ids, MESSAGEBOX_STUCK_SENDING_ALERT_REDIS_PREFIX
        )

        current_app.logger.error(
            "Messagebox notifications stuck sending",
            extra={
                "number_of_notifications": len(stuck_sending),
                "notification_ids": notification_ids,
                "new_or_due_for_re_alert": due_notification_ids,
            },
        )

        if due_notification_ids and current_app.should_send_zendesk_alerts:
            msg = (
                f"{len(due_notification_ids)} messagebox notifications have been sending for over "
                f"{max_hours_ago_to_check_sending} hours with no result from ebms-core. Do not resend. "
                f"Re-alerted at most once per {MESSAGEBOX_STUCK_ALERT_COOLDOWN_SECONDS // 3600}h per "
                "notification while still stuck. See the messagebox flow doc's troubleshooting section "
                "(docs/notification-flows/messagebox.md) for how to tell an external Logius-side gap apart "
                "from a local poller/processing issue before escalating.\n\n"
                f"Notifications: {due_notification_ids}"
            )
            environment = current_app.config["NOTIFY_ENVIRONMENT"]
            ticket = NotifySupportTicket(
                subject=f"[{environment}] Messagebox notifications stuck sending",
                message=msg,
                ticket_type=NotifySupportTicket.TYPE_TASK,
                notify_ticket_type=NotifyTicketType.TECHNICAL,
                notify_task_type="notify_task_messagebox_stuck_sending",
            )
            zendesk_client.send_ticket_to_zendesk(ticket)
            _mark_notifications_alerted(due_notification_ids, MESSAGEBOX_STUCK_SENDING_ALERT_REDIS_PREFIX)
