from datetime import date, datetime
from decimal import Decimal

from freezegun import freeze_time

from app.dao.fact_billing_dao import (
    fetch_usage_for_all_services_letter_breakdown,
    get_rate,
    get_rates_for_billing,
)
from tests.app.db import (
    create_letter_rate,
    create_rate,
    set_up_usage_data,
)


@freeze_time("2017-06-01 12:00")
def test_get_rate(notify_db_session):
    create_rate(start_date=datetime(2017, 5, 30, 23, 0), value=1.2, notification_type="email")
    create_rate(start_date=datetime(2017, 5, 30, 23, 0), value=2.2, notification_type="sms")
    create_rate(start_date=datetime(2017, 5, 30, 23, 0), value=3.3, notification_type="email")
    create_letter_rate(start_date=datetime(2017, 5, 30, 23, 0), rate=0.66, post_class="international")
    create_letter_rate(start_date=datetime(2017, 5, 30, 23, 0), rate=0.3, post_class="netherlands")

    non_letter_rates, letter_rates = get_rates_for_billing()
    rate = get_rate(
        non_letter_rates=non_letter_rates, letter_rates=letter_rates, notification_type="sms", date=date(2017, 6, 1)
    )
    letter_rate = get_rate(
        non_letter_rates=non_letter_rates,
        letter_rates=letter_rates,
        notification_type="letter",
        crown=True,
        letter_page_count=1,
        date=date(2017, 6, 1),
    )

    assert rate == 2.2
    assert letter_rate == Decimal("0.3")


def test_fetch_usage_for_all_services_letter_breakdown(notify_db_session):
    fixtures = set_up_usage_data(datetime(2019, 6, 1))

    results = fetch_usage_for_all_services_letter_breakdown(datetime(2019, 6, 1), datetime(2019, 9, 30)).all()

    assert len(results) == 8
    assert results[0] == (
        fixtures["org_1"].name,
        fixtures["org_1"].id,
        fixtures["service_1_sms_and_letter"].name,
        fixtures["service_1_sms_and_letter"].id,
        Decimal("0.35"),
        "netherlands",
        2,
    )
    assert results[1] == (
        fixtures["org_1"].name,
        fixtures["org_1"].id,
        fixtures["service_1_sms_and_letter"].name,
        fixtures["service_1_sms_and_letter"].id,
        Decimal("0.45"),
        "netherlands",
        6,
    )
    assert results[2] == (
        fixtures["org_for_service_with_letters"].name,
        fixtures["org_for_service_with_letters"].id,
        fixtures["service_with_letters"].name,
        fixtures["service_with_letters"].id,
        Decimal("0.50"),
        "netherlands",
        2,
    )
    assert results[3] == (
        fixtures["org_for_service_with_letters"].name,
        fixtures["org_for_service_with_letters"].id,
        fixtures["service_with_letters"].name,
        fixtures["service_with_letters"].id,
        Decimal("0.65"),
        "netherlands",
        20,
    )
    assert results[4] == (
        None,
        None,
        fixtures["service_with_letters_without_org"].name,
        fixtures["service_with_letters_without_org"].id,
        Decimal("0.35"),
        "netherlands",
        2,
    )
    assert results[5] == (
        None,
        None,
        fixtures["service_with_letters_without_org"].name,
        fixtures["service_with_letters_without_org"].id,
        Decimal("0.50"),
        "netherlands",
        1,
    )
    assert results[6] == (
        None,
        None,
        fixtures["service_with_letters_without_org"].name,
        fixtures["service_with_letters_without_org"].id,
        Decimal("0.64"),
        "netherlands",
        3,
    )
    assert results[7] == (
        None,
        None,
        fixtures["service_with_letters_without_org"].name,
        fixtures["service_with_letters_without_org"].id,
        Decimal("1.55"),
        "international",
        15,
    )
