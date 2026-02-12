from datetime import datetime, timedelta
from decimal import Decimal

from app.celery.reporting_tasks import (
    create_or_update_ft_billing_for_day,
)
from app.constants import (
    EMAIL_TYPE,
    LETTER_TYPE,
    SMS_TYPE,
)
from app.models import FactBilling
from tests.app.db import (
    create_notification,
    create_notification_history,
    create_template,
)


def sample_letter_template(sample_service_full_permissions):
    return create_template(sample_service_full_permissions, template_type=LETTER_TYPE, postage="netherlands")


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


def test_create_or_update_ft_billing_for_day_checks_history(sample_service, sample_letter_template, mocker):
    yesterday = datetime.now() - timedelta(days=1)
    mocker.patch("app.dao.fact_billing_dao.get_rate", side_effect=mocker_get_rate)

    create_notification(
        created_at=yesterday,
        template=sample_letter_template,
        status="sending",
    )

    create_notification_history(
        created_at=yesterday,
        template=sample_letter_template,
        status="delivered",
    )

    records = FactBilling.query.all()
    assert len(records) == 0

    create_or_update_ft_billing_for_day(str(yesterday.date()))
    records = FactBilling.query.all()
    assert len(records) == 1

    record = records[0]
    assert record.notification_type == LETTER_TYPE
    assert record.notifications_sent == 2
