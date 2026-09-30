"""NotifyNL twins of the upstream provider-stats tests, which only expect mmg/firetext.

Spryng is an active SMS provider for NotifyNL (and the priority one in our fixtures), so the
new upstream delivery stats must include it.
"""

from datetime import timedelta
from unittest.mock import call

from app import db
from app.celery.scheduled_tasks import generate_sms_delivery_stats
from app.dao.notifications_dao import (
    get_banded_slow_text_message_delivery_reports_by_provider,
    get_recent_undelivered_notification_ages,
)
from app.otel_metrics.provider import _priority as provider_priority_metric


def test_get_recent_undelivered_notification_ages_includes_spryng(notify_db_session):
    result = get_recent_undelivered_notification_ages(
        (timedelta(seconds=30), timedelta(seconds=60), timedelta(seconds=90)), session=db.session
    )

    for key_type in ("normal", "team", "test"):
        assert result[("spryng", "sms", key_type)] == (0, 0, 0)


def test_get_banded_slow_text_message_delivery_reports_includes_spryng(notify_db_session):
    result = get_banded_slow_text_message_delivery_reports_by_provider(
        ((timedelta(minutes=5), timedelta(minutes=10)),), session=db.session
    )

    assert "spryng" in result


def test_generate_sms_delivery_stats_records_spryng_priority(notify_api, mocker):
    mocker.patch("app.celery.scheduled_tasks.get_recent_undelivered_notification_ages", return_value={})
    mocker.patch("app.celery.scheduled_tasks.get_slow_text_message_delivery_reports_by_provider", return_value=[])
    mocker.patch(
        "app.celery.scheduled_tasks.get_banded_slow_text_message_delivery_reports_by_provider", return_value={}
    )
    priority_metric_mock = mocker.patch.object(provider_priority_metric, "set")

    generate_sms_delivery_stats()

    assert call(100, {"provider.name": "spryng"}) in priority_metric_mock.call_args_list
