from datetime import datetime

from app.dao.notifications_dao import (
    dao_get_letters_and_sheets_volume_by_postage,
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
