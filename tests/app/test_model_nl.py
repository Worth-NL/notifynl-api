import pytest

from tests.app.db import (
    create_notification,
)


@pytest.mark.parametrize("status", ["created", "pending-virus-check"])
def test_notification_serialize_with_cost_data_for_letter_when_data_not_ready(
    client, sample_letter_template, letter_rate, status
):
    notification = create_notification(
        sample_letter_template, billable_units=None, postage="netherlands", status=status
    )

    response = notification.serialize_with_cost_data()

    assert response["is_cost_data_ready"] is False
    assert response["cost_details"] == {}
    assert response["cost_in_pounds"] is None


@pytest.mark.parametrize("status", ["validation-failed", "technical-failure", "cancelled", "virus-scan-failed"])
def test_notification_serialize_with_with_cost_data_for_letter_that_wasnt_sent(
    client, sample_letter_template, letter_rate, status
):
    notification = create_notification(sample_letter_template, billable_units=1, postage="netherlands", status=status)

    response = notification.serialize_with_cost_data()

    assert response["is_cost_data_ready"] is True
    assert response["cost_details"] == {"billable_sheets_of_paper": 0, "postage": "netherlands"}
    assert response["cost_in_pounds"] == 0.00
