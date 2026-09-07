from datetime import datetime, timedelta

from app.dao.notifications_dao import (
    dao_get_letters_and_sheets_volume_by_postage,
    dao_messagebox_notifications_still_pending,
    dao_messagebox_notifications_stuck_sending,
)
from tests.app.db import (
    create_notification,
    create_service,
    create_template,
)


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
