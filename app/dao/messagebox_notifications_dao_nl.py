from sqlalchemy import func

from app import db
from app.constants import MESSAGEBOX_TYPE, NOTIFICATION_SENDING, NOTIFICATION_TECHNICAL_FAILURE
from app.models import Notification


def dao_messagebox_notifications_sending_to_check(*, older_than, newer_than, limit):
    """Messagebox notifications in `sending` whose ebms-core delivery status
    should be checked (see messagebox_check_sending_status): ebms-core accepted
    them, and `reference` holds its ebMS message id, but the counterparty can
    still reject them at ebMS level, in which case no async
    BerichtVerwerkResponse ever arrives.

    `older_than` gives ebms-core time for its first delivery attempt;
    `newer_than` stops checking notifications long past any ebMS TimeToLive,
    which the stuck-sending alert of check_if_messagebox_still_pending covers."""
    return (
        Notification.query.filter(
            Notification.notification_type == MESSAGEBOX_TYPE,
            Notification.status == NOTIFICATION_SENDING,
            Notification.reference.isnot(None),
            func.coalesce(Notification.updated_at, Notification.created_at) < older_than,
            Notification.created_at > newer_than,
        )
        .order_by(Notification.created_at)
        .limit(limit)
        .all()
    )


def dao_messagebox_notifications_technical_failure_between(start, end):
    """Id, detailed_status_code and key_type of the messagebox notifications that moved to technical-failure in
    [start, end), going by `updated_at`, which the status change sets. Non-overlapping windows from an hourly check
    report each failure once. Only those columns, since a broken delivery chain can fail thousands in an hour."""
    return (
        db.session.query(Notification.id, Notification.detailed_status_code, Notification.key_type)
        .filter(
            Notification.notification_type == MESSAGEBOX_TYPE,
            Notification.status == NOTIFICATION_TECHNICAL_FAILURE,
            Notification.updated_at >= start,
            Notification.updated_at < end,
        )
        .order_by(Notification.updated_at)
        .all()
    )
