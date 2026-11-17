from datetime import UTC, datetime, timedelta

import pytest

from tests.app.db import create_letter_rate, create_notification


@pytest.fixture
def letter_rate(notify_db_session):
    # the shared fixture is a UK "second" class rate
    return create_letter_rate(start_date=datetime.now(UTC) - timedelta(days=1), post_class="netherlands")


@pytest.mark.parametrize("sent_by", ["pingen", "rest-endpoint"])
def test_get_letter_accepted_by_its_print_provider(api_client_request, sample_letter_template, letter_rate, sent_by):
    notification = create_notification(template=sample_letter_template, status="sent", sent_by=sent_by)

    json_response = api_client_request.get(
        notification.service_id,
        "v2_notifications.get_notification_by_id",
        notification_id=notification.id,
    )

    assert json_response["status"] == "sent"
    assert json_response["print_provider"] == sent_by


def test_get_letter_not_yet_accepted_by_a_print_provider(api_client_request, sample_letter_template, letter_rate):
    # sent_by is only set once the print provider accepted the letter
    notification = create_notification(template=sample_letter_template, status="sending")

    json_response = api_client_request.get(
        notification.service_id,
        "v2_notifications.get_notification_by_id",
        notification_id=notification.id,
    )

    assert json_response["status"] == "accepted"
    assert json_response["print_provider"] is None


@pytest.mark.parametrize("filter_status, expected_statuses", [("accepted", ["accepted"]), ("sent", ["sent"])])
def test_get_letter_notifications_filtered_on_acceptance_by_the_print_provider(
    api_client_request, sample_letter_template, letter_rate, filter_status, expected_statuses
):
    create_notification(template=sample_letter_template, status="sending")
    create_notification(template=sample_letter_template, status="sent", sent_by="pingen")

    json_response = api_client_request.get(
        sample_letter_template.service_id,
        "v2_notifications.get_notifications",
        status=filter_status,
    )

    assert [n["status"] for n in json_response["notifications"]] == expected_statuses
    if filter_status == "sent":
        assert json_response["notifications"][0]["print_provider"] == "pingen"
