import logging
import uuid
from datetime import datetime

import sentry_sdk
from flask import current_app

from app import notify_celery, statsd_client
from app.clients import ClientException
from app.clients.messagebox.ebms_adapter import get_messagebox_responses
from app.config import TaskNamesNL
from app.constants import NOTIFICATION_PENDING
from app.dao import notifications_dao
from app.notifications.notifications_ses_callback import (
    check_and_queue_callback_task,
)


@notify_celery.task(
    bind=True,
    name=TaskNamesNL.MESSAGEBOX_PROCESS_CALLBACKS,
    max_retries=5,
    default_retry_delay=300,
    early_log_level=logging.DEBUG,
)
def process_messagebox_client_response(
    self, status, provider_reference, client_name, detailed_status_code=None, stadium=None, envelope_id=None
):
    # validate reference
    try:
        uuid.UUID(provider_reference, version=4)
    except ValueError as e:
        current_app.logger.exception("%s callback with invalid reference %s", client_name, provider_reference)
        raise e

    response_parser = get_messagebox_responses

    # validate status
    try:
        notification_status, detailed_status = response_parser(status, detailed_status_code)
    except KeyError as e:
        _process_for_status(
            notification_status="technical-failure",
            client_name=client_name,
            provider_reference=provider_reference,
            envelope_id=envelope_id,
            ebms_status=status,
        )
        raise ClientException(f"{client_name} callback failed: status {status} not found.") from e

    _process_for_status(
        notification_status=notification_status,
        client_name=client_name,
        provider_reference=provider_reference,
        detailed_status_code=detailed_status_code,
        stadium=stadium,
        envelope_id=envelope_id,
        ebms_status=status,
        notify_detailed_status=detailed_status,
    )


def _process_for_status(
    notification_status,
    client_name,
    provider_reference,
    detailed_status_code=None,
    stadium=None,
    envelope_id=None,
    ebms_status=None,
    notify_detailed_status=None,
):
    matched_notification = notifications_dao.get_notification_by_id(provider_reference)

    sentry_sdk.set_tag("notification_id", provider_reference)

    log_extra = {
        "envelope_id": envelope_id,
        "message_id": provider_reference,
        "matched_notification_id": str(matched_notification.id) if matched_notification else None,
        "ebms_status": ebms_status,
        "ebms_process_code": detailed_status_code,
        "ebms_stadium": stadium,
        "notify_status": notification_status,
        "notify_detailed_status": notify_detailed_status,
    }

    notification = notifications_dao.update_notification_status_by_id(
        notification_id=provider_reference,
        status=notification_status,
        detailed_status_code=detailed_status_code,
        messagebox_stadium=stadium,
    )

    if not matched_notification:
        current_app.logger.warning(
            "%s callback for messagebox message %s in envelope %s: no matching notification found (unmatched) -- "
            "ebms status=%s(%s) stadium=%s",
            client_name,
            provider_reference,
            envelope_id,
            notification_status,
            ebms_status,
            stadium,
            extra=log_extra,
        )
        return

    if not notification:
        current_app.logger.info(
            "%s callback for messagebox message %s in envelope %s: matched notification %s not updated "
            "(already in terminal state)",
            client_name,
            provider_reference,
            envelope_id,
            matched_notification.id,
            extra=log_extra,
        )
        return

    current_app.logger.info(
        "%s callback for messagebox message %s in envelope %s: matched notification %s, ebms status=%s(%s) "
        "stadium=%s -> notify status=%s(%s)",
        client_name,
        provider_reference,
        envelope_id,
        notification.id,
        detailed_status_code,
        ebms_status,
        stadium,
        notification_status,
        notify_detailed_status,
        extra=log_extra,
    )

    statsd_client.incr(f"callback.{client_name.lower()}.{notification_status}")

    if notification.sent_at:
        statsd_client.timing_with_dates(
            f"callback.{client_name.lower()}.{notification_status}.elapsed-time",
            datetime.utcnow(),
            notification.sent_at,
        )

    if notification_status != NOTIFICATION_PENDING:
        check_and_queue_callback_task(notification)
