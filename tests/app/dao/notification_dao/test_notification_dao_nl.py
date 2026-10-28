import uuid
from datetime import datetime, timedelta

import pytest
from freezegun import freeze_time

from app import db
from app.constants import (
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_TEMPORARY_FAILURE,
)
from app.dao.notifications_dao import (
    BandedSlowProviderDeliveryReport,
    dao_cancel_letter_if_still_cancellable,
    dao_claim_letter_for_sending,
    dao_get_letters_abandoned_sending,
    dao_get_letters_and_sheets_volume_by_postage,
    dao_get_letters_ready_to_send_since,
    dao_get_letters_stuck_sending,
    dao_mark_letter_sent,
    dao_messagebox_notifications_still_pending,
    dao_messagebox_notifications_stuck_sending,
    dao_touch_notification,
    dao_update_letter_status_from_provider,
    get_banded_slow_text_message_delivery_reports_by_provider,
    get_recent_undelivered_notification_ages,
)
from app.models import Notification, NotificationHistory
from tests.app.db import (
    create_notification,
    create_notification_history,
    create_service,
    create_template,
)
from tests.utils import QueryRecorder


def test_dao_get_letters_and_sheets_volume_by_postage(notify_db_session):
    first_service = create_service(
        service_name="first service",
        service_id="3a5cea08-29fd-4bb9-b582-8dedd928b149",
    )
    second_service = create_service(
        service_name="second service",
        service_id="642bf33b-54b5-45f2-8c13-942a46616704",
    )

    first_template = create_template(service=first_service, template_type="letter", postage="netherlands")
    second_template = create_template(service=second_service, template_type="letter", postage="netherlands")

    create_notification(template=first_template, created_at=datetime(2020, 12, 1, 12, 30), postage="europe")
    create_notification(template=first_template, created_at=datetime(2020, 12, 1, 13, 30), postage="rest-of-world")
    create_notification(template=first_template, created_at=datetime(2020, 12, 1, 9, 30), postage="netherlands")
    create_notification(template=first_template, created_at=datetime(2020, 12, 1, 14, 30), billable_units=3)
    create_notification(template=first_template, created_at=datetime(2020, 12, 1, 14, 30), billable_units=0)
    create_notification(template=first_template, created_at=datetime(2020, 12, 1, 15, 30))
    create_notification(template=second_template, created_at=datetime(2020, 12, 1, 8, 30), postage="netherlands")
    create_notification(template=second_template, created_at=datetime(2020, 12, 1, 8, 31), postage="netherlands")
    create_notification(template=second_template, created_at=datetime(2020, 12, 1, 8, 32))
    create_notification(template=second_template, created_at=datetime(2020, 12, 1, 8, 33))
    create_notification(template=second_template, created_at=datetime(2020, 12, 1, 8, 34))

    results = dao_get_letters_and_sheets_volume_by_postage(print_run_deadline_local=datetime(2020, 12, 1, 17, 30))

    # After merging first, second and economy into "netherlands"
    assert len(results) == 3

    expected_results = [
        {"letters_count": 1, "sheets_count": 1, "postage": "europe"},
        {"letters_count": 1, "sheets_count": 1, "postage": "rest-of-world"},
        {"letters_count": 8, "sheets_count": 10, "postage": "netherlands"},
    ]

    for result in results:
        assert result._asdict() in expected_results


def test_dao_messagebox_notifications_still_pending(notify_db_session):
    service = create_service()
    messagebox_template = create_template(service=service, template_type="messagebox")
    email_template = create_template(service=service, template_type="email")

    cutoff_time = datetime.utcnow() - timedelta(minutes=60)
    old = datetime.utcnow() - timedelta(minutes=120)
    recent = datetime.utcnow()

    stuck_pending_virus_check = create_notification(
        template=messagebox_template, status="pending-virus-check", created_at=old
    )
    stuck_created = create_notification(template=messagebox_template, status="created", created_at=old)
    # not returned: "sending" means ebms-core already accepted it -- must never be
    # blindly resent, see test_dao_messagebox_notifications_stuck_sending instead.
    create_notification(template=messagebox_template, status="sending", created_at=old)
    # not stuck: too recent
    create_notification(template=messagebox_template, status="created", created_at=recent)
    # not stuck: already delivered
    create_notification(template=messagebox_template, status="delivered", created_at=old)
    # not messagebox
    create_notification(template=email_template, status="created", created_at=old)

    results = dao_messagebox_notifications_still_pending(cutoff_time)

    assert {n.id for n in results} == {stuck_pending_virus_check.id, stuck_created.id}


def test_dao_messagebox_notifications_stuck_sending(notify_db_session):
    service = create_service()
    messagebox_template = create_template(service=service, template_type="messagebox")
    email_template = create_template(service=service, template_type="email")

    cutoff_time = datetime.utcnow() - timedelta(hours=24)
    old = datetime.utcnow() - timedelta(hours=48)
    recent = datetime.utcnow()

    stuck_sending = create_notification(template=messagebox_template, status="sending", created_at=old)
    # not stuck: too recent
    create_notification(template=messagebox_template, status="sending", created_at=recent)
    # not stuck: not sending
    create_notification(template=messagebox_template, status="created", created_at=old)
    # not messagebox
    create_notification(template=email_template, status="sending", created_at=old)

    results = dao_messagebox_notifications_stuck_sending(cutoff_time)

    assert {n.id for n in results} == {stuck_sending.id}


@pytest.mark.parametrize("status", ["created", "pending-virus-check"])
def test_dao_cancel_letter_if_still_cancellable_cancels_letter(sample_letter_template, status):
    notification = create_notification(template=sample_letter_template, status=status)

    cancelled = dao_cancel_letter_if_still_cancellable(notification.id)

    assert cancelled.id == notification.id
    assert cancelled.status == "cancelled"


@pytest.mark.parametrize("status", ["sending", "sent", "delivered", "technical-failure", "cancelled"])
def test_dao_cancel_letter_if_still_cancellable_leaves_letter_already_past_cancelling(sample_letter_template, status):
    notification = create_notification(template=sample_letter_template, status=status)

    assert dao_cancel_letter_if_still_cancellable(notification.id) is None
    assert notification.status == status


def test_dao_claim_letter_for_sending_claims_a_letter_only_once(sample_letter_template):
    notification = create_notification(template=sample_letter_template, status="created")

    assert dao_claim_letter_for_sending(notification.id) is True
    assert dao_claim_letter_for_sending(notification.id) is False
    assert Notification.query.get(notification.id).status == "sending"


@pytest.mark.parametrize("status", ["pending-virus-check", "sending", "sent", "cancelled", "technical-failure"])
def test_dao_claim_letter_for_sending_only_claims_created_letters(sample_letter_template, status):
    notification = create_notification(template=sample_letter_template, status=status)

    assert dao_claim_letter_for_sending(notification.id) is False
    assert Notification.query.get(notification.id).status == status


def test_dao_claim_letter_for_sending_only_claims_letters(sample_email_template):
    notification = create_notification(template=sample_email_template, status="created")

    assert dao_claim_letter_for_sending(notification.id) is False


@freeze_time("2026-09-29 12:00")
def test_dao_mark_letter_sent(sample_letter_template):
    notification = create_notification(template=sample_letter_template, status="sending")

    assert dao_mark_letter_sent(notification.id, "pingen") is True

    notification = Notification.query.get(notification.id)
    assert (notification.status, notification.sent_by) == ("sent", "pingen")
    assert notification.sent_at == datetime(2026, 9, 29, 12, 0)


@pytest.mark.parametrize("status", ["created", "delivered", "technical-failure"])
def test_dao_mark_letter_sent_only_from_sending(sample_letter_template, status):
    # e.g. a provider that reports back before our delivery task gets to mark the letter sent
    notification = create_notification(template=sample_letter_template, status=status)

    assert dao_mark_letter_sent(notification.id, "rest-endpoint") is False
    assert Notification.query.get(notification.id).status == status


@freeze_time("2026-09-29 12:00")
def test_dao_update_letter_status_from_provider(sample_letter_template):
    notification = create_notification(template=sample_letter_template, status="sending")

    assert dao_update_letter_status_from_provider(
        notification.id, "technical-failure", {"sending", "sent"}, "pingen", detailed_status_code="print-provider-issue"
    )

    notification = Notification.query.get(notification.id)
    assert (notification.status, notification.detailed_status_code) == ("technical-failure", "print-provider-issue")
    assert (notification.sent_by, notification.sent_at) == ("pingen", datetime(2026, 9, 29, 12, 0))
    assert notification.updated_at == datetime(2026, 9, 29, 12, 0)


def test_dao_update_letter_status_from_provider_keeps_the_send_details(sample_letter_template):
    notification = create_notification(
        template=sample_letter_template, status="sent", sent_by="rest-endpoint", sent_at=datetime(2026, 9, 29, 9, 0)
    )

    assert dao_update_letter_status_from_provider(notification.id, "delivered", {"sending", "sent"}, "pingen")

    notification = Notification.query.get(notification.id)
    assert (notification.status, notification.detailed_status_code) == ("delivered", None)
    assert (notification.sent_by, notification.sent_at) == ("rest-endpoint", datetime(2026, 9, 29, 9, 0))


def test_dao_update_letter_status_from_provider_only_from_the_given_statuses(sample_letter_template):
    notification = create_notification(template=sample_letter_template, status="delivered")

    assert not dao_update_letter_status_from_provider(notification.id, "delivered", {"sending", "sent"}, "pingen")
    assert Notification.query.get(notification.id).status == "delivered"


@pytest.mark.parametrize("from_status, expected_status", [("sent", "delivered"), ("permanent-failure", None)])
def test_dao_update_letter_status_from_provider_in_notification_history(
    sample_letter_template, from_status, expected_status
):
    notification = create_notification_history(template=sample_letter_template, status=from_status)

    updated = dao_update_letter_status_from_provider(notification.id, "delivered", {"sending", "sent"}, "pingen")

    assert updated is (expected_status is not None)
    assert NotificationHistory.query.get(notification.id).status == (expected_status or from_status)


def test_dao_update_letter_status_from_provider_for_an_unknown_letter(notify_db_session):
    assert not dao_update_letter_status_from_provider(uuid.uuid4(), "delivered", {"sending", "sent"}, "pingen")


def test_dao_touch_notification(sample_letter_template):
    notification = create_notification(template=sample_letter_template, status="sending")

    with freeze_time("2026-09-29 13:00"):
        dao_touch_notification(notification.id)

    assert Notification.query.get(notification.id).updated_at == datetime(2026, 9, 29, 13, 0)


@freeze_time("2026-09-29 12:00")
def test_dao_get_letters_ready_to_send_since(sample_letter_template, sample_email_template):
    old = datetime(2026, 9, 29, 11, 30)
    ready = create_notification(template=sample_letter_template, status="created", created_at=old, billable_units=1)
    create_notification(template=sample_letter_template, status="created", created_at=datetime(2026, 9, 29, 11, 55))
    create_notification(template=sample_letter_template, status="created", created_at=old, billable_units=0)
    create_notification(template=sample_letter_template, status="created", created_at=old, key_type="test")
    create_notification(template=sample_letter_template, status="sending", created_at=old, billable_units=1)
    create_notification(template=sample_email_template, status="created", created_at=old)
    recently_updated = create_notification(template=sample_letter_template, status="created", created_at=old)
    recently_updated.updated_at = datetime(2026, 9, 29, 11, 50)

    assert dao_get_letters_ready_to_send_since(datetime(2026, 9, 29, 11, 45)) == [ready.id]


@freeze_time("2026-09-29 12:00")
def test_dao_get_letters_stuck_sending(sample_letter_template):
    six_am = datetime(2026, 9, 29, 6)
    stuck = create_notification(template=sample_letter_template, status="sending", created_at=six_am, updated_at=six_am)
    # a retry touched it recently
    create_notification(
        template=sample_letter_template, status="sending", created_at=six_am, updated_at=datetime(2026, 9, 29, 11, 57)
    )
    create_notification(template=sample_letter_template, status="sent", created_at=six_am, updated_at=six_am)
    create_notification(
        template=sample_letter_template, status="sending", created_at=six_am, updated_at=six_am, key_type="test"
    )
    # sent through notifynl-dvla-service, whose alerts cover it
    create_notification(
        template=sample_letter_template, status="sending", created_at=six_am, updated_at=six_am, sent_by="dvla"
    )

    assert dao_get_letters_stuck_sending(datetime(2026, 9, 29, 8)) == [stuck]


@freeze_time("2026-09-29 12:00")
def test_dao_get_letters_abandoned_sending(sample_letter_template):
    def letter(last_touched, **kwargs):
        return create_notification(
            template=sample_letter_template,
            status=kwargs.pop("status", "sending"),
            created_at=datetime(2026, 9, 29, 6),
            updated_at=last_touched,
            **kwargs,
        )

    abandoned = letter(datetime(2026, 9, 29, 11, 30))
    letter(datetime(2026, 9, 29, 11, 57))  # a retry touched it recently
    letter(datetime(2026, 9, 29, 7))  # left alone for too long: the stuck-sending alert's
    letter(datetime(2026, 9, 29, 11, 30), status="sent")
    letter(datetime(2026, 9, 29, 11, 30), key_type="test")
    letter(datetime(2026, 9, 29, 11, 30), sent_by="dvla")

    assert dao_get_letters_abandoned_sending(datetime(2026, 9, 29, 11, 45), not_before=datetime(2026, 9, 29, 8)) == [
        abandoned.id
    ]


# Twins of the upstream provider-stats tests. NotifyNL also has Spryng and the Pingen and REST endpoint print
# providers, and keeps MMG inactive: the undelivered-age report lists those with zero counts, and the banded reports
# (active providers only) use Spryng where upstream uses MMG.


def _tds(s):
    return timedelta(seconds=s)


@pytest.mark.parametrize(
    "notifications,expected_result",
    (
        (
            (
                # no notifications
            ),
            {
                ("dvla", "letter", "normal"): (0, 0, 0),
                ("dvla", "letter", "team"): (0, 0, 0),
                ("dvla", "letter", "test"): (0, 0, 0),
                ("firetext", "sms", "normal"): (0, 0, 0),
                ("firetext", "sms", "team"): (0, 0, 0),
                ("firetext", "sms", "test"): (0, 0, 0),
                ("mmg", "sms", "normal"): (0, 0, 0),
                ("mmg", "sms", "team"): (0, 0, 0),
                ("mmg", "sms", "test"): (0, 0, 0),
                ("pingen", "letter", "normal"): (0, 0, 0),
                ("pingen", "letter", "team"): (0, 0, 0),
                ("pingen", "letter", "test"): (0, 0, 0),
                ("rest-endpoint", "letter", "normal"): (0, 0, 0),
                ("rest-endpoint", "letter", "team"): (0, 0, 0),
                ("rest-endpoint", "letter", "test"): (0, 0, 0),
                ("ses", "email", "normal"): (0, 0, 0),
                ("ses", "email", "team"): (0, 0, 0),
                ("ses", "email", "test"): (0, 0, 0),
                ("spryng", "sms", "normal"): (0, 0, 0),
                ("spryng", "sms", "team"): (0, 0, 0),
                ("spryng", "sms", "test"): (0, 0, 0),
            },
        ),
        (
            (
                (_tds(60), _tds(55), NOTIFICATION_SENDING, {"sent_by": "mmg"}),
                (_tds(61), _tds(55), NOTIFICATION_SENDING, {"sent_by": "mmg"}),
                (_tds(62), _tds(60), NOTIFICATION_SENDING, {"sent_by": "mmg"}),
                (_tds(63), _tds(61), NOTIFICATION_SENDING, {"sent_by": "mmg"}),
                (_tds(64), _tds(62), NOTIFICATION_DELIVERED, {"sent_by": "mmg"}),  # excluded
                (_tds(130), _tds(81), NOTIFICATION_PENDING, {"sent_by": "mmg"}),
                (_tds(300), _tds(120), NOTIFICATION_SENDING, {"sent_by": "mmg"}),  # excluded
                (_tds(1500), _tds(85), NOTIFICATION_PENDING, {"sent_by": "mmg"}),  # excluded
                (_tds(33), _tds(32), NOTIFICATION_PENDING, {"sent_by": "mmg", "key_type": KEY_TYPE_TEST}),
                (_tds(10), _tds(9), NOTIFICATION_SENDING, {"sent_by": "firetext"}),
                (_tds(5), _tds(4), NOTIFICATION_DELIVERED, {"sent_by": "firetext"}),  # excluded
                (_tds(39), _tds(10), NOTIFICATION_PENDING, {"sent_by": "firetext", "key_type": KEY_TYPE_TEAM}),
                (_tds(50), _tds(11), NOTIFICATION_SENDING, {"sent_by": "firetext", "key_type": KEY_TYPE_TEAM}),
                (_tds(61), _tds(12), NOTIFICATION_PENDING, {"sent_by": "firetext"}),
                (
                    _tds(62),
                    _tds(62),
                    NOTIFICATION_DELIVERED,
                    {"sent_by": "firetext", "key_type": KEY_TYPE_TEST},
                ),  # excluded
                (_tds(300), _tds(50), NOTIFICATION_DELIVERED, {"sent_by": "firetext"}),  # excluded
            ),
            {
                ("dvla", "letter", "normal"): (0, 0, 0),
                ("dvla", "letter", "team"): (0, 0, 0),
                ("dvla", "letter", "test"): (0, 0, 0),
                ("firetext", "sms", "normal"): (2, 2, 2),
                ("firetext", "sms", "team"): (2, 2, 2),
                ("firetext", "sms", "test"): (0, 0, 0),
                ("mmg", "sms", "normal"): (0, 3, 5),
                ("mmg", "sms", "team"): (0, 0, 0),
                ("mmg", "sms", "test"): (0, 1, 1),
                ("pingen", "letter", "normal"): (0, 0, 0),
                ("pingen", "letter", "team"): (0, 0, 0),
                ("pingen", "letter", "test"): (0, 0, 0),
                ("rest-endpoint", "letter", "normal"): (0, 0, 0),
                ("rest-endpoint", "letter", "team"): (0, 0, 0),
                ("rest-endpoint", "letter", "test"): (0, 0, 0),
                ("ses", "email", "normal"): (0, 0, 0),
                ("ses", "email", "team"): (0, 0, 0),
                ("ses", "email", "test"): (0, 0, 0),
                ("spryng", "sms", "normal"): (0, 0, 0),
                ("spryng", "sms", "team"): (0, 0, 0),
                ("spryng", "sms", "test"): (0, 0, 0),
            },
        ),
        (
            (
                (
                    _tds(10),
                    _tds(1),
                    NOTIFICATION_DELIVERED,
                    {"sent_by": "firetext", "key_type": KEY_TYPE_TEAM},
                ),  # excluded
                (_tds(2), _tds(2), NOTIFICATION_PERMANENT_FAILURE, {"sent_by": "firetext"}),  # excluded
                (
                    _tds(50),
                    _tds(11),
                    NOTIFICATION_DELIVERED,
                    {"sent_by": "firetext", "key_type": KEY_TYPE_TEAM},
                ),  # excluded
                (_tds(100), _tds(99), NOTIFICATION_SENDING, {"sent_by": "firetext"}),  # excluded
                (_tds(80), _tds(80), NOTIFICATION_SENT, {"sent_by": "firetext"}),  # excluded
                (_tds(1), _tds(1), NOTIFICATION_SENDING, {"sent_by": "mmg", "key_type": KEY_TYPE_TEST}),
                (_tds(123), _tds(1), NOTIFICATION_SENDING, {"sent_by": "mmg", "key_type": KEY_TYPE_TEST}),
                (_tds(90), _tds(90), NOTIFICATION_SENDING, {"sent_by": "mmg", "key_type": KEY_TYPE_TEST}),
            ),
            {
                ("dvla", "letter", "normal"): (0, 0, 0),
                ("dvla", "letter", "team"): (0, 0, 0),
                ("dvla", "letter", "test"): (0, 0, 0),
                ("firetext", "sms", "normal"): (0, 0, 0),
                ("firetext", "sms", "team"): (0, 0, 0),
                ("firetext", "sms", "test"): (0, 0, 0),
                ("mmg", "sms", "normal"): (0, 0, 0),
                ("mmg", "sms", "team"): (0, 0, 0),
                ("mmg", "sms", "test"): (2, 2, 3),
                ("pingen", "letter", "normal"): (0, 0, 0),
                ("pingen", "letter", "team"): (0, 0, 0),
                ("pingen", "letter", "test"): (0, 0, 0),
                ("rest-endpoint", "letter", "normal"): (0, 0, 0),
                ("rest-endpoint", "letter", "team"): (0, 0, 0),
                ("rest-endpoint", "letter", "test"): (0, 0, 0),
                ("ses", "email", "normal"): (0, 0, 0),
                ("ses", "email", "team"): (0, 0, 0),
                ("ses", "email", "test"): (0, 0, 0),
                ("spryng", "sms", "normal"): (0, 0, 0),
                ("spryng", "sms", "team"): (0, 0, 0),
                ("spryng", "sms", "test"): (0, 0, 0),
            },
        ),
    ),
)
@pytest.mark.parametrize(
    "session,expected_bind_key",
    (
        (db.session, None),
        (db.session_bulk, "bulk"),
    ),
    ids=("default", "bulk"),
)
@freeze_time()
def test_get_recent_undelivered_notification_ages(
    notify_db_session, sample_template, notifications, session, expected_result, expected_bind_key
):
    uniform_now = datetime.now()

    for created_delta, sent_delta, status, options in notifications:
        created_at = uniform_now - created_delta
        sent_at = uniform_now - sent_delta
        create_notification(
            template=sample_template,
            sent_at=sent_at,
            created_at=created_at,
            status=status,
            updated_at=sent_at,
            **options,
        )

    with QueryRecorder() as query_recorder:
        assert (
            get_recent_undelivered_notification_ages(
                (_tds(30), _tds(60), _tds(90)), created_sent_difference_allowance=timedelta(minutes=15), session=session
            )
            == expected_result
        )

    assert {query_info.bind_key for query_info in query_recorder.queries} == {expected_bind_key}


@pytest.mark.parametrize(
    "bands,notifications,expected_result",
    (
        (
            (
                (_tds(60), _tds(120)),
                (_tds(120), _tds(240)),
            ),
            (
                (_tds(55), NOTIFICATION_SENDING, None, {"sent_by": "spryng"}),  # excluded
                (_tds(61), NOTIFICATION_SENDING, None, {"sent_by": "spryng"}),  # slow
                (_tds(118), NOTIFICATION_DELIVERED, _tds(5), {"sent_by": "spryng"}),  # ok
                (_tds(123), NOTIFICATION_PENDING, _tds(5), {"sent_by": "spryng"}),  # slow
                (_tds(124), NOTIFICATION_DELIVERED, _tds(5), {"sent_by": "spryng"}),  # ok
                (_tds(125), NOTIFICATION_DELIVERED, _tds(5), {"sent_by": "spryng"}),  # ok
                (_tds(128), NOTIFICATION_DELIVERED, _tds(61), {"sent_by": "spryng"}),  # ok
                (_tds(236), NOTIFICATION_DELIVERED, _tds(130), {"sent_by": "spryng"}),  # slow
                (_tds(244), NOTIFICATION_DELIVERED, _tds(130), {"sent_by": "spryng"}),  # excluded
                (_tds(65), NOTIFICATION_SENDING, None, {"sent_by": "firetext"}),  # slow
                (_tds(66), NOTIFICATION_DELIVERED, _tds(5), {"sent_by": "firetext"}),  # ok
                (_tds(111), NOTIFICATION_DELIVERED, _tds(66), {"sent_by": "firetext"}),  # slow
                (_tds(112), NOTIFICATION_PENDING, _tds(5), {"sent_by": "firetext"}),  # slow
                (_tds(122), NOTIFICATION_PENDING, _tds(5), {"sent_by": "firetext"}),  # slow
                (_tds(222), NOTIFICATION_DELIVERED, _tds(5), {"sent_by": "firetext"}),  # ok
                (_tds(223), NOTIFICATION_DELIVERED, _tds(121), {"sent_by": "firetext"}),  # slow
                (_tds(224), NOTIFICATION_DELIVERED, _tds(115), {"sent_by": "firetext"}),  # ok
            ),
            {
                "spryng": (
                    BandedSlowProviderDeliveryReport(
                        provider="spryng",
                        slow_ratio=0.5,
                        slow_notifications=1,
                        total_notifications=2,
                        delivered_within=_tds(60),
                        sent_after_ago=_tds(120),
                    ),
                    BandedSlowProviderDeliveryReport(
                        provider="spryng",
                        slow_ratio=0.4,
                        slow_notifications=2,
                        total_notifications=5,
                        delivered_within=_tds(120),
                        sent_after_ago=_tds(240),
                    ),
                ),
                "firetext": (
                    BandedSlowProviderDeliveryReport(
                        provider="firetext",
                        slow_ratio=0.75,
                        slow_notifications=3,
                        total_notifications=4,
                        delivered_within=_tds(60),
                        sent_after_ago=_tds(120),
                    ),
                    BandedSlowProviderDeliveryReport(
                        provider="firetext",
                        slow_ratio=0.5,
                        slow_notifications=2,
                        total_notifications=4,
                        delivered_within=_tds(120),
                        sent_after_ago=_tds(240),
                    ),
                ),
            },
        ),
        (
            ((_tds(30), _tds(60)),),
            (
                (_tds(29), NOTIFICATION_SENDING, None, {"sent_by": "spryng"}),  # excluded
                (_tds(30), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "spryng"}),  # excluded
                (_tds(32), NOTIFICATION_TEMPORARY_FAILURE, _tds(31), {"sent_by": "spryng"}),  # excluded
                (_tds(35), NOTIFICATION_PERMANENT_FAILURE, _tds(31), {"sent_by": "spryng"}),  # excluded
                (_tds(36), NOTIFICATION_SENDING, None, {"sent_by": "spryng", "key_type": KEY_TYPE_TEST}),  # excluded
                (_tds(60.1), NOTIFICATION_PENDING, _tds(1), {"sent_by": "spryng"}),  # excluded
                (_tds(40), NOTIFICATION_SENT, _tds(32), {"sent_by": "firetext"}),  # excluded
                (_tds(41), NOTIFICATION_PENDING, _tds(10), {"sent_by": "firetext"}),  # slow
                (_tds(60), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "firetext"}),  # ok
            ),
            {
                "spryng": (
                    BandedSlowProviderDeliveryReport(
                        provider="spryng",
                        slow_ratio=0.0,
                        slow_notifications=0,
                        total_notifications=0,
                        delivered_within=_tds(30),
                        sent_after_ago=_tds(60),
                    ),
                ),
                "firetext": (
                    BandedSlowProviderDeliveryReport(
                        provider="firetext",
                        slow_ratio=0.5,
                        slow_notifications=1,
                        total_notifications=2,
                        delivered_within=_tds(30),
                        sent_after_ago=_tds(60),
                    ),
                ),
            },
        ),
        (
            (
                (_tds(30), _tds(60)),
                (_tds(60), _tds(70)),
                (_tds(70), _tds(80)),
            ),
            (
                (_tds(31), NOTIFICATION_DELIVERED, _tds(30), {"sent_by": "spryng"}),  # slow
                (_tds(60), NOTIFICATION_DELIVERED, _tds(60), {"sent_by": "spryng"}),  # slow
                (_tds(70), NOTIFICATION_DELIVERED, _tds(70), {"sent_by": "spryng"}),  # slow
                (_tds(80), NOTIFICATION_DELIVERED, _tds(80), {"sent_by": "spryng"}),  # slow
                (_tds(40), NOTIFICATION_PENDING, _tds(10), {"sent_by": "firetext"}),  # slow
            ),
            {
                "spryng": (
                    BandedSlowProviderDeliveryReport(
                        provider="spryng",
                        slow_ratio=1.0,
                        slow_notifications=2,
                        total_notifications=2,
                        delivered_within=_tds(30),
                        sent_after_ago=_tds(60),
                    ),
                    BandedSlowProviderDeliveryReport(
                        provider="spryng",
                        slow_ratio=1.0,
                        slow_notifications=1,
                        total_notifications=1,
                        delivered_within=_tds(60),
                        sent_after_ago=_tds(70),
                    ),
                    BandedSlowProviderDeliveryReport(
                        provider="spryng",
                        slow_ratio=1.0,
                        slow_notifications=1,
                        total_notifications=1,
                        delivered_within=_tds(70),
                        sent_after_ago=_tds(80),
                    ),
                ),
                "firetext": (
                    BandedSlowProviderDeliveryReport(
                        provider="firetext",
                        slow_ratio=1.0,
                        slow_notifications=1,
                        total_notifications=1,
                        delivered_within=_tds(30),
                        sent_after_ago=_tds(60),
                    ),
                    BandedSlowProviderDeliveryReport(
                        provider="firetext",
                        slow_ratio=0.0,
                        slow_notifications=0,
                        total_notifications=0,
                        delivered_within=_tds(60),
                        sent_after_ago=_tds(70),
                    ),
                    BandedSlowProviderDeliveryReport(
                        provider="firetext",
                        slow_ratio=0.0,
                        slow_notifications=0,
                        total_notifications=0,
                        delivered_within=_tds(70),
                        sent_after_ago=_tds(80),
                    ),
                ),
            },
        ),
    ),
)
@pytest.mark.parametrize(
    "session,expected_bind_key",
    (
        (db.session, None),
        (db.session_bulk, "bulk"),
    ),
    ids=("default", "bulk"),
)
@freeze_time()
def test_get_banded_slow_text_message_delivery_reports_by_provider(
    notify_db_session, sample_template, bands, notifications, session, expected_result, expected_bind_key
):
    uniform_now = datetime.now()

    for created_sent_delta, status, updated_at_delta, options in notifications:
        created_sent = uniform_now - created_sent_delta
        create_notification(
            template=sample_template,
            sent_at=created_sent,
            created_at=created_sent,
            status=status,
            updated_at=created_sent + (updated_at_delta or timedelta()),
            **options,
        )

    with QueryRecorder() as query_recorder:
        assert get_banded_slow_text_message_delivery_reports_by_provider(bands, session=session) == expected_result

    assert {query_info.bind_key for query_info in query_recorder.queries} == {expected_bind_key}


@pytest.mark.parametrize(
    "bands,notifications,expected_result",
    (
        (
            ((_tds(60), _tds(120)),),
            (
                (_tds(60), _tds(55), NOTIFICATION_SENDING, None, {"sent_by": "spryng"}),  # excluded
                (_tds(61), _tds(55), NOTIFICATION_SENDING, None, {"sent_by": "spryng"}),  # excluded
                (_tds(62), _tds(60), NOTIFICATION_SENDING, None, {"sent_by": "spryng"}),  # excluded
                (_tds(63), _tds(61), NOTIFICATION_SENDING, None, {"sent_by": "spryng"}),  # slow
                (_tds(130), _tds(110), NOTIFICATION_SENDING, None, {"sent_by": "spryng"}),  # slow
                (_tds(300), _tds(120), NOTIFICATION_SENDING, None, {"sent_by": "spryng"}),  # slow
                (_tds(1120), _tds(119), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "spryng"}),  # excluded
                (_tds(60), _tds(59), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "firetext"}),  # excluded
                (_tds(61), _tds(60), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "firetext"}),  # excluded
                (_tds(100), _tds(70), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "firetext"}),  # ok
                (_tds(100), _tds(70), NOTIFICATION_DELIVERED, _tds(65), {"sent_by": "firetext"}),  # slow
                (_tds(300), _tds(50), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "firetext"}),  # excluded
            ),
            {
                "spryng": (
                    BandedSlowProviderDeliveryReport(
                        provider="spryng",
                        slow_ratio=1.0,
                        slow_notifications=3,
                        total_notifications=3,
                        delivered_within=_tds(60),
                        sent_after_ago=_tds(120),
                    ),
                ),
                "firetext": (
                    BandedSlowProviderDeliveryReport(
                        provider="firetext",
                        slow_ratio=0.5,
                        slow_notifications=1,
                        total_notifications=2,
                        delivered_within=_tds(60),
                        sent_after_ago=_tds(120),
                    ),
                ),
            },
        ),
        (
            (
                # misordered and overlapping bands should "work" but aren't advisable
                (_tds(80), _tds(90)),
                (_tds(60), _tds(140)),
                (_tds(25), _tds(50)),
            ),
            (
                (_tds(24), _tds(23), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "spryng"}),  # excluded
                (_tds(25), _tds(24), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "spryng"}),  # excluded
                (_tds(26), _tds(25), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "spryng"}),  # excluded
                (_tds(27), _tds(26), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "spryng"}),  # ok
                (_tds(28), _tds(27), NOTIFICATION_PENDING, _tds(26), {"sent_by": "spryng"}),  # slow
                (_tds(95), _tds(85), NOTIFICATION_DELIVERED, _tds(61), {"sent_by": "spryng"}),  # 2 bands, ok/slow
                (_tds(1000), _tds(86), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "spryng"}),  # 2 bands, ok/ok
                (_tds(1000.1), _tds(86.1), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "spryng"}),  # 2 bands, ok/ok
                (_tds(1000.2), _tds(86.2), NOTIFICATION_DELIVERED, _tds(1), {"sent_by": "spryng"}),  # 2 bands, ok/ok
                (_tds(1001), _tds(87), NOTIFICATION_SENDING, None, {"sent_by": "spryng"}),  # 2 bands, slow/slow
                (_tds(1100), _tds(88), NOTIFICATION_SENDING, None, {"sent_by": "spryng"}),  # excluded
                (_tds(1101), _tds(110), NOTIFICATION_SENDING, None, {"sent_by": "spryng"}),  # excluded
                (_tds(800), _tds(111), NOTIFICATION_DELIVERED, _tds(60), {"sent_by": "spryng"}),  # ok
                (_tds(55), _tds(54), NOTIFICATION_SENDING, None, {"sent_by": "firetext"}),  # excluded
                (_tds(90), _tds(55), NOTIFICATION_SENDING, None, {"sent_by": "firetext"}),  # excluded
                (_tds(300), _tds(56), NOTIFICATION_SENDING, None, {"sent_by": "firetext"}),  # excluded
                (_tds(301), _tds(57), NOTIFICATION_DELIVERED, _tds(56), {"sent_by": "firetext"}),  # excluded
                (_tds(302), _tds(62), NOTIFICATION_DELIVERED, _tds(10), {"sent_by": "firetext"}),  # ok
            ),
            {
                "spryng": (
                    BandedSlowProviderDeliveryReport(
                        provider="spryng",
                        slow_ratio=0.2,
                        slow_notifications=1,
                        total_notifications=5,
                        delivered_within=_tds(80),
                        sent_after_ago=_tds(90),
                    ),
                    BandedSlowProviderDeliveryReport(
                        provider="spryng",
                        slow_ratio=0.5,
                        slow_notifications=3,
                        total_notifications=6,
                        delivered_within=_tds(60),
                        sent_after_ago=_tds(140),
                    ),
                    BandedSlowProviderDeliveryReport(
                        provider="spryng",
                        slow_ratio=0.5,
                        slow_notifications=1,
                        total_notifications=2,
                        delivered_within=_tds(25),
                        sent_after_ago=_tds(50),
                    ),
                ),
                "firetext": (
                    BandedSlowProviderDeliveryReport(
                        provider="firetext",
                        slow_ratio=0.0,
                        slow_notifications=0,
                        total_notifications=0,
                        delivered_within=_tds(80),
                        sent_after_ago=_tds(90),
                    ),
                    BandedSlowProviderDeliveryReport(
                        provider="firetext",
                        slow_ratio=0.0,
                        slow_notifications=0,
                        total_notifications=1,
                        delivered_within=_tds(60),
                        sent_after_ago=_tds(140),
                    ),
                    BandedSlowProviderDeliveryReport(
                        provider="firetext",
                        slow_ratio=0.0,
                        slow_notifications=0,
                        total_notifications=0,
                        delivered_within=_tds(25),
                        sent_after_ago=_tds(50),
                    ),
                ),
            },
        ),
    ),
)
@pytest.mark.parametrize(
    "session,expected_bind_key",
    (
        (db.session, None),
        (db.session_bulk, "bulk"),
    ),
    ids=("default", "bulk"),
)
@freeze_time()
def test_get_banded_slow_text_message_delivery_reports_by_provider_created_at_sent_at(
    notify_db_session, sample_template, bands, notifications, session, expected_result, expected_bind_key
):
    uniform_now = datetime.now()

    for created_delta, sent_delta, status, updated_at_delta, options in notifications:
        created_at = uniform_now - created_delta
        sent_at = uniform_now - sent_delta
        create_notification(
            template=sample_template,
            sent_at=sent_at,
            created_at=created_at,
            status=status,
            updated_at=sent_at + (updated_at_delta or timedelta()),
            **options,
        )

    with QueryRecorder() as query_recorder:
        assert (
            get_banded_slow_text_message_delivery_reports_by_provider(
                bands, created_sent_difference_allowance=timedelta(minutes=15), session=session
            )
            == expected_result
        )

    assert {query_info.bind_key for query_info in query_recorder.queries} == {expected_bind_key}
