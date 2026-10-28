from datetime import datetime, timedelta
from unittest import mock
from unittest.mock import ANY, call

import pytest
from freezegun import freeze_time
from notifications_utils.clients.zendesk.zendesk_client import (
    NotifySupportTicket,
    NotifyTicketType,
)
from notifications_utils.testing.comparisons import RestrictedAny

from app.celery.scheduled_tasks import (
    check_if_letters_still_pending_virus_check,
    generate_sms_delivery_stats,
)
from app.config import QueueNames, TaskNames
from app.constants import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING_VIRUS_CHECK,
)
from app.dao.notifications_dao import BandedSlowProviderDeliveryReport, SlowProviderDeliveryReport
from app.otel_metrics.notification import (
    _undelivered_notification_age as notification_undelivered_notification_age_metric,
)
from app.otel_metrics.provider import (
    _info as provider_info_metric,
)
from app.otel_metrics.provider import (
    _priority as provider_priority_metric,
)
from app.otel_metrics.provider import (
    _sms_banded_not_delivered_within as provider_sms_banded_not_delivered_within_metric,
)
from app.otel_metrics.provider import (
    _sms_banded_not_delivered_within_absolute as provider_sms_banded_not_delivered_within_absolute_metric,
)
from app.otel_metrics.provider import (
    _sms_banded_not_delivered_within_total as provider_sms_banded_not_delivered_within_total_metric,
)
from app.otel_metrics.provider import (
    _sms_legacy_not_delivered_within as provider_sms_legacy_not_delivered_within_metric,
)
from app.otel_metrics.provider import (
    _updated_at as provider_updated_at_metric,
)
from tests.app.db import (
    create_notification,
)
from tests.conftest import set_config


@freeze_time("2019-05-30 14:00:00")
def test_check_if_letters_still_pending_virus_check_raises_zendesk_if_files_cant_be_found(
    sample_letter_template, mocker
):
    mock_file_exists = mocker.patch("app.aws.s3.file_exists", return_value=False)
    mocker.patch("app.celery.scheduled_tasks.get_letter_attachment_keys", return_value=[])
    mock_create_ticket = mocker.spy(NotifySupportTicket, "__init__")
    mock_celery = mocker.patch("app.celery.scheduled_tasks.notify_celery.send_task")
    mock_send_ticket_to_zendesk = mocker.patch(
        "app.celery.scheduled_tasks.zendesk_client.send_ticket_to_zendesk",
        autospec=True,
    )

    create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(seconds=600),
        reference="ignore as still has time",
    )
    create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_DELIVERED,
        created_at=datetime.utcnow() - timedelta(seconds=1000),
        reference="ignore as status in delivered",
    )
    notification_1 = create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(seconds=601),
        reference="one",
    )
    notification_2 = create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(seconds=1000),
        reference="two",
    )

    check_if_letters_still_pending_virus_check()

    assert mock_file_exists.call_count == 2
    mock_file_exists.assert_has_calls(
        [
            call("test-letters-scan", "NOTIFY.ONE.D.1.C.20190530134959.PDF"),
            call("test-letters-scan", "NOTIFY.TWO.D.1.C.20190530134320.PDF"),
        ],
        any_order=True,
    )
    assert mock_celery.called is False

    mock_create_ticket.assert_called_once_with(
        ANY,
        subject="[test] Letters still pending virus check",
        message=ANY,
        ticket_type="task",
        notify_ticket_type=NotifyTicketType.TECHNICAL,
        notify_task_type="notify_task_letters_pending_scan",
    )
    assert "2 precompiled letters have been pending-virus-check" in mock_create_ticket.call_args.kwargs["message"]
    assert f"{(str(notification_1.id), notification_1.reference)}" in mock_create_ticket.call_args.kwargs["message"]
    assert f"{(str(notification_2.id), notification_2.reference)}" in mock_create_ticket.call_args.kwargs["message"]
    mock_send_ticket_to_zendesk.assert_called_once()


@freeze_time("2019-05-30 14:00:00")
def test_check_if_letters_still_pending_virus_check_restarts_scan_for_stuck_letters(mocker, sample_letter_template):
    mock_file_exists = mocker.patch("app.aws.s3.file_exists", return_value=True)
    mock_create_ticket = mocker.spy(NotifySupportTicket, "__init__")
    mock_celery = mocker.patch("app.celery.scheduled_tasks.notify_celery.send_task")

    create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(minutes=10, seconds=1),
        reference="one",
    )
    create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(minutes=9, seconds=59),
        reference="still has time to send",
    )
    create_notification(
        template=sample_letter_template,
        status=NOTIFICATION_PENDING_VIRUS_CHECK,
        created_at=datetime.utcnow() - timedelta(minutes=30, seconds=1),
        reference="too old for us to bother with",
    )
    expected_filename = "NOTIFY.ONE.D.1.C.20190530134959.PDF"

    check_if_letters_still_pending_virus_check()

    mock_file_exists.assert_called_once_with("test-letters-scan", expected_filename)

    mock_celery.assert_called_once_with(
        name=TaskNames.SCAN_FILE,
        kwargs={"filename": expected_filename},
        queue=QueueNames.ANTIVIRUS,
        MessageGroupId=str(sample_letter_template.service_id),
    )

    assert mock_create_ticket.called is False


# Twin of the upstream test: NotifyNL also has Spryng (the priority provider in tests), MMG is inactive and
# Firetext supports international SMS.
@pytest.mark.parametrize(
    "slow_delivery_config_option, expect_check_slow_delivery",
    (
        (
            False,
            False,
        ),
        (
            True,
            True,
        ),
    ),
)
def test_generate_sms_delivery_stats(slow_delivery_config_option, expect_check_slow_delivery, notify_api, mocker):
    undelivered_notification_age_metric_set_mock = mocker.patch.object(
        notification_undelivered_notification_age_metric, "set"
    )
    sms_not_delivered_within_metric_set_mock = mocker.patch.object(
        provider_sms_legacy_not_delivered_within_metric, "set"
    )
    sms_banded_not_delivered_within_metric_set_mock = mocker.patch.object(
        provider_sms_banded_not_delivered_within_metric, "set"
    )
    sms_banded_not_delivered_within_absolute_metric_set_mock = mocker.patch.object(
        provider_sms_banded_not_delivered_within_absolute_metric, "set"
    )
    sms_banded_not_delivered_within_total_metric_set_mock = mocker.patch.object(
        provider_sms_banded_not_delivered_within_total_metric, "set"
    )
    priority_metric_mock = mocker.patch.object(provider_priority_metric, "set")
    updated_at_metric_mock = mocker.patch.object(provider_updated_at_metric, "set")
    info_metric_mock = mocker.patch.object(provider_info_metric, "set")

    mock_get_recent_undelivered_notification_ages = mocker.patch(
        "app.celery.scheduled_tasks.get_recent_undelivered_notification_ages",
        return_value={
            ("mmg", "sms", "normal"): tuple(range(3)),
            ("mmg", "sms", "test"): tuple(range(6, 3, -1)),
            ("firetext", "sms", "normal"): tuple(range(10, 13)),
            ("ses", "email", "normal"): tuple(range(20, 23)),
        },
    )
    # reduce the volume of args/output we need to mock
    mocker.patch(
        "app.celery.scheduled_tasks.UNDELIVERED_NOTIFICATION_AGE_HISTOGRAM_BUCKETS",
        [20, 30, 40],
    )

    slow_delivery_reports = [
        SlowProviderDeliveryReport(provider="mmg", slow_ratio=0.4, slow_notifications=40, total_notifications=100),
        SlowProviderDeliveryReport(provider="firetext", slow_ratio=0.8, slow_notifications=80, total_notifications=100),
    ]
    mock_get_slow_text_message_delivery_reports_by_provider = mocker.patch(
        "app.celery.scheduled_tasks.get_slow_text_message_delivery_reports_by_provider",
        return_value=slow_delivery_reports,
    )

    banded_slow_delivery_reports = {
        "mmg": (
            BandedSlowProviderDeliveryReport(
                provider="mmg",
                slow_ratio=0.4,
                slow_notifications=40,
                total_notifications=100,
                sent_after_ago=timedelta(seconds=120),
                delivered_within=timedelta(seconds=60),
            ),
            BandedSlowProviderDeliveryReport(
                provider="mmg",
                slow_ratio=0.45,
                slow_notifications=45,
                total_notifications=100,
                sent_after_ago=timedelta(seconds=240),
                delivered_within=timedelta(seconds=120),
            ),
        ),
        "firetext": (
            BandedSlowProviderDeliveryReport(
                provider="firetext",
                slow_ratio=0.8,
                slow_notifications=80,
                total_notifications=100,
                sent_after_ago=timedelta(seconds=120),
                delivered_within=timedelta(seconds=60),
            ),
            BandedSlowProviderDeliveryReport(
                provider="firetext",
                slow_ratio=0.85,
                slow_notifications=85,
                total_notifications=100,
                sent_after_ago=timedelta(seconds=240),
                delivered_within=timedelta(seconds=120),
            ),
        ),
    }
    mock_get_banded_slow_text_message_delivery_reports_by_provider = mocker.patch(
        "app.celery.scheduled_tasks.get_banded_slow_text_message_delivery_reports_by_provider",
        return_value=banded_slow_delivery_reports,
    )

    mock_check_slow_delivery = mocker.patch(
        "app.celery.scheduled_tasks._check_slow_text_message_delivery_reports_and_raise_error_if_needed"
    )

    with set_config(notify_api, "CHECK_SLOW_TEXT_MESSAGE_DELIVERY", slow_delivery_config_option):
        generate_sms_delivery_stats()

    assert mock_get_recent_undelivered_notification_ages.call_args_list == [
        call((timedelta(seconds=20), timedelta(seconds=30), timedelta(seconds=40)), session=mock.ANY)
    ]

    assert mock_get_slow_text_message_delivery_reports_by_provider.call_args_list == [
        call(created_within_minutes=15, delivered_within_minutes=1),
        call(created_within_minutes=15, delivered_within_minutes=5),
        call(created_within_minutes=15, delivered_within_minutes=10),
    ]

    assert mock_get_banded_slow_text_message_delivery_reports_by_provider.call_args_list == [
        call(
            (
                (timedelta(seconds=30), timedelta(seconds=60)),
                (timedelta(seconds=60), timedelta(seconds=120)),
                (timedelta(seconds=120), timedelta(seconds=240)),
                (timedelta(seconds=240), timedelta(seconds=480)),
                (timedelta(seconds=480), timedelta(seconds=960)),
            ),
            session=mock.ANY,
        )
    ]

    assert mock_check_slow_delivery.call_args_list == (
        [call(slow_delivery_reports)] if expect_check_slow_delivery else []
    )

    # normalizing order of following calls by sorting by sorted attribute k/v pairs

    assert sorted(
        undelivered_notification_age_metric_set_mock.mock_calls, key=lambda c: sorted(c.args[1].items())
    ) == sorted(
        (
            call(
                20,
                {
                    "key.type": "normal",
                    "notification.type": "email",
                    "provider.name": "ses",
                    "time_window.evaluation": 40.0,
                    "le": 20.0,
                },
            ),
            call(
                10,
                {
                    "key.type": "normal",
                    "notification.type": "sms",
                    "provider.name": "firetext",
                    "time_window.evaluation": 40.0,
                    "le": 20.0,
                },
            ),
            call(
                0,
                {
                    "key.type": "normal",
                    "notification.type": "sms",
                    "provider.name": "mmg",
                    "time_window.evaluation": 40.0,
                    "le": 20.0,
                },
            ),
            call(
                21,
                {
                    "key.type": "normal",
                    "notification.type": "email",
                    "provider.name": "ses",
                    "time_window.evaluation": 40.0,
                    "le": 30.0,
                },
            ),
            call(
                11,
                {
                    "key.type": "normal",
                    "notification.type": "sms",
                    "provider.name": "firetext",
                    "time_window.evaluation": 40.0,
                    "le": 30.0,
                },
            ),
            call(
                1,
                {
                    "key.type": "normal",
                    "notification.type": "sms",
                    "provider.name": "mmg",
                    "time_window.evaluation": 40.0,
                    "le": 30.0,
                },
            ),
            call(
                22,
                {
                    "key.type": "normal",
                    "notification.type": "email",
                    "provider.name": "ses",
                    "time_window.evaluation": 40.0,
                    "le": 40.0,
                },
            ),
            call(
                12,
                {
                    "key.type": "normal",
                    "notification.type": "sms",
                    "provider.name": "firetext",
                    "time_window.evaluation": 40.0,
                    "le": 40.0,
                },
            ),
            call(
                2,
                {
                    "key.type": "normal",
                    "notification.type": "sms",
                    "provider.name": "mmg",
                    "time_window.evaluation": 40.0,
                    "le": 40.0,
                },
            ),
            call(
                6,
                {
                    "key.type": "test",
                    "notification.type": "sms",
                    "provider.name": "mmg",
                    "time_window.evaluation": 40.0,
                    "le": 20.0,
                },
            ),
            call(
                5,
                {
                    "key.type": "test",
                    "notification.type": "sms",
                    "provider.name": "mmg",
                    "time_window.evaluation": 40.0,
                    "le": 30.0,
                },
            ),
            call(
                4,
                {
                    "key.type": "test",
                    "notification.type": "sms",
                    "provider.name": "mmg",
                    "time_window.evaluation": 40.0,
                    "le": 40.0,
                },
            ),
        ),
        key=lambda c: sorted(c.args[1].items()),
    )

    assert sorted(
        sms_not_delivered_within_metric_set_mock.mock_calls, key=lambda c: sorted(c.args[1].items())
    ) == sorted(
        (
            call(0.4, {"provider.name": "mmg", "time_window.evaluation": 900, "time_window.delivery": 60}),
            call(0.8, {"provider.name": "firetext", "time_window.evaluation": 900, "time_window.delivery": 60}),
            call(0.4, {"provider.name": "mmg", "time_window.evaluation": 900, "time_window.delivery": 300}),
            call(0.8, {"provider.name": "firetext", "time_window.evaluation": 900, "time_window.delivery": 300}),
            call(0.4, {"provider.name": "mmg", "time_window.evaluation": 900, "time_window.delivery": 600}),
            call(0.8, {"provider.name": "firetext", "time_window.evaluation": 900, "time_window.delivery": 600}),
        ),
        key=lambda c: sorted(c.args[1].items()),
    )

    assert sorted(
        sms_banded_not_delivered_within_metric_set_mock.mock_calls, key=lambda c: sorted(c.args[1].items())
    ) == sorted(
        (
            call(
                0.8,
                {
                    "provider.name": "firetext",
                    "time_window.evaluation": 60.0,
                    "time_window.delivery": 60.0,
                    "time_window.delay": 60.0,
                },
            ),
            call(
                0.85,
                {
                    "provider.name": "firetext",
                    "time_window.evaluation": 120.0,
                    "time_window.delivery": 120.0,
                    "time_window.delay": 120.0,
                },
            ),
            call(
                0.4,
                {
                    "provider.name": "mmg",
                    "time_window.evaluation": 60.0,
                    "time_window.delivery": 60.0,
                    "time_window.delay": 60.0,
                },
            ),
            call(
                0.45,
                {
                    "provider.name": "mmg",
                    "time_window.evaluation": 120.0,
                    "time_window.delivery": 120.0,
                    "time_window.delay": 120.0,
                },
            ),
        ),
        key=lambda c: sorted(c.args[1].items()),
    )

    assert sorted(
        sms_banded_not_delivered_within_absolute_metric_set_mock.mock_calls, key=lambda c: sorted(c.args[1].items())
    ) == sorted(
        (
            call(
                80,
                {
                    "provider.name": "firetext",
                    "time_window.evaluation": 60.0,
                    "time_window.delivery": 60.0,
                    "time_window.delay": 60.0,
                },
            ),
            call(
                85,
                {
                    "provider.name": "firetext",
                    "time_window.evaluation": 120.0,
                    "time_window.delivery": 120.0,
                    "time_window.delay": 120.0,
                },
            ),
            call(
                40,
                {
                    "provider.name": "mmg",
                    "time_window.evaluation": 60.0,
                    "time_window.delivery": 60.0,
                    "time_window.delay": 60.0,
                },
            ),
            call(
                45,
                {
                    "provider.name": "mmg",
                    "time_window.evaluation": 120.0,
                    "time_window.delivery": 120.0,
                    "time_window.delay": 120.0,
                },
            ),
        ),
        key=lambda c: sorted(c.args[1].items()),
    )

    assert sorted(
        sms_banded_not_delivered_within_total_metric_set_mock.mock_calls, key=lambda c: sorted(c.args[1].items())
    ) == sorted(
        (
            call(
                100,
                {
                    "provider.name": "firetext",
                    "time_window.evaluation": 60.0,
                    "time_window.delivery": 60.0,
                    "time_window.delay": 60.0,
                },
            ),
            call(
                100,
                {
                    "provider.name": "firetext",
                    "time_window.evaluation": 120.0,
                    "time_window.delivery": 120.0,
                    "time_window.delay": 120.0,
                },
            ),
            call(
                100,
                {
                    "provider.name": "mmg",
                    "time_window.evaluation": 60.0,
                    "time_window.delivery": 60.0,
                    "time_window.delay": 60.0,
                },
            ),
            call(
                100,
                {
                    "provider.name": "mmg",
                    "time_window.evaluation": 120.0,
                    "time_window.delivery": 120.0,
                    "time_window.delay": 120.0,
                },
            ),
        ),
        key=lambda c: sorted(c.args[1].items()),
    )

    assert sorted(priority_metric_mock.mock_calls, key=lambda c: sorted(c.args[1].items())) == sorted(
        (
            call(0, {"provider.name": "firetext"}),
            call(0, {"provider.name": "mmg"}),
            call(100, {"provider.name": "spryng"}),
        ),
        key=lambda c: sorted(c.args[1].items()),
    )

    assert sorted(updated_at_metric_mock.mock_calls, key=lambda c: sorted(c.args[1].items())) == sorted(
        (
            call(RestrictedAny(lambda x: x < datetime.utcnow().timestamp()), {"provider.name": "firetext"}),
            call(RestrictedAny(lambda x: x < datetime.utcnow().timestamp()), {"provider.name": "mmg"}),
            call(RestrictedAny(lambda x: x < datetime.utcnow().timestamp()), {"provider.name": "spryng"}),
        ),
        key=lambda c: sorted(c.args[1].items()),
    )

    assert sorted(info_metric_mock.mock_calls, key=lambda c: sorted(c.args[1].items())) == sorted(
        (
            call(
                1,
                {
                    "provider.name": "firetext",
                    "provider.active": True,
                    "provider.supports_international": True,
                    "notification.type": "sms",
                },
            ),
            call(
                1,
                {
                    "provider.name": "mmg",
                    "provider.active": False,
                    "provider.supports_international": True,
                    "notification.type": "sms",
                },
            ),
            call(
                1,
                {
                    "provider.name": "spryng",
                    "provider.active": True,
                    "provider.supports_international": True,
                    "notification.type": "sms",
                },
            ),
        ),
        key=lambda c: sorted(c.args[1].items()),
    )
