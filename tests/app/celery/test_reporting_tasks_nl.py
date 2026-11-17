from datetime import date, datetime
from decimal import Decimal

from app.constants import (
    EMAIL_TYPE,
    LETTER_TYPE,
    SMS_TYPE,
)
from app.dao.fact_billing_dao import get_rate
from tests.app.db import (
    create_letter_rate,
)


def mocker_get_rate(
    non_letter_rates,
    letter_rates,
    notification_type,
    bst_date,
    crown=None,
    rate_multiplier=None,
    post_class="netherlands",
):
    if notification_type == LETTER_TYPE:
        return Decimal(2.1)
    elif notification_type == SMS_TYPE:
        return Decimal(1.33)
    elif notification_type == EMAIL_TYPE:
        return Decimal(0)


# TODO: refactor crown out of letters
def test_get_rate_for_letter_latest(notify_db_session):
    # letter rates should be passed into the get_rate function as a tuple of start_date, crown, sheet_count,
    # rate and post_class
    new = create_letter_rate(datetime(2017, 12, 1), crown=True, sheet_count=1, rate=0.33, post_class="netherlands")
    old = create_letter_rate(datetime(2016, 12, 1), crown=True, sheet_count=1, rate=0.30, post_class="netherlands")
    letter_rates = [new, old]

    rate = get_rate([], letter_rates, LETTER_TYPE, date(2018, 1, 1), True, 1)
    assert rate == Decimal("0.33")


def test_get_rate_for_letter_latest_if_crown_is_none(notify_db_session):
    # letter rates should be passed into the get_rate function as a tuple of start_date, crown, sheet_count,
    # rate and post_class
    crown = create_letter_rate(datetime(2017, 12, 1), crown=True, sheet_count=1, rate=0.33, post_class="netherlands")
    non_crown = create_letter_rate(
        datetime(2017, 12, 1), crown=False, sheet_count=1, rate=0.35, post_class="netherlands"
    )
    letter_rates = [crown, non_crown]

    rate = get_rate([], letter_rates, LETTER_TYPE, date(2018, 1, 1), crown=None, letter_page_count=1)
    assert rate == Decimal("0.33")
