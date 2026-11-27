from datetime import datetime, timedelta

from app.dao.messagebox_notifications_dao_nl import (
    dao_messagebox_notifications_sending_to_check,
    dao_messagebox_notifications_technical_failure_between,
)
from tests.app.db import create_notification, create_service, create_template


def test_dao_messagebox_notifications_sending_to_check(notify_db_session):
    service = create_service()
    messagebox_template = create_template(service=service, template_type="messagebox")
    email_template = create_template(service=service, template_type="email")

    now = datetime.utcnow()
    older_than = now - timedelta(minutes=5)
    newer_than = now - timedelta(days=7)
    sent = now - timedelta(minutes=30)

    def sending(template=messagebox_template, status="sending", reference="ebms-1", created_at=sent, updated_at=sent):
        return create_notification(
            template=template, status=status, reference=reference, created_at=created_at, updated_at=updated_at
        )

    to_check = sending()
    # not checked: sent to ebms-core too recently
    sending(created_at=now, updated_at=now)
    # not checked: older than the window (the stuck-sending alert covers it)
    sending(created_at=now - timedelta(days=8), updated_at=now - timedelta(days=8))
    # not checked: no ebMS message id to look up
    sending(reference=None)
    # not checked: not sending
    sending(status="delivered")
    # not messagebox
    sending(template=email_template)

    results = dao_messagebox_notifications_sending_to_check(older_than=older_than, newer_than=newer_than, limit=10)

    assert [n.id for n in results] == [to_check.id]


def test_dao_messagebox_notifications_sending_to_check_limits_oldest_first(notify_db_session):
    service = create_service()
    messagebox_template = create_template(service=service, template_type="messagebox")
    now = datetime.utcnow()

    oldest, middle, _newest = (
        create_notification(
            template=messagebox_template,
            status="sending",
            reference=f"ebms-{minutes}",
            created_at=now - timedelta(minutes=minutes),
            updated_at=now - timedelta(minutes=minutes),
        )
        for minutes in (60, 40, 20)
    )

    results = dao_messagebox_notifications_sending_to_check(
        older_than=now - timedelta(minutes=5), newer_than=now - timedelta(days=7), limit=2
    )

    assert [n.id for n in results] == [oldest.id, middle.id]


def test_dao_messagebox_notifications_technical_failure_between(notify_db_session):
    service = create_service()
    messagebox_template = create_template(service=service, template_type="messagebox")
    email_template = create_template(service=service, template_type="email")

    start = datetime(2026, 11, 27, 11, 0)
    end = datetime(2026, 11, 27, 12, 0)

    def notification(template=messagebox_template, status="technical-failure", updated_at=start):
        return create_notification(
            template=template, status=status, created_at=updated_at - timedelta(minutes=10), updated_at=updated_at
        )

    at_start = notification()
    just_before_end = notification(updated_at=end - timedelta(seconds=1))
    # not in the window: before it, or at its end (which is the next window's start)
    notification(updated_at=start - timedelta(seconds=1))
    notification(updated_at=end)
    # not technical-failure
    notification(status="permanent-failure", updated_at=start + timedelta(minutes=30))
    # not messagebox
    notification(template=email_template, updated_at=start + timedelta(minutes=30))

    results = dao_messagebox_notifications_technical_failure_between(start, end)

    assert [n.id for n in results] == [at_start.id, just_before_end.id]
