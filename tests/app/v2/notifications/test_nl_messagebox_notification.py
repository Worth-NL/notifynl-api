import pytest

from app.constants import MESSAGEBOX_TYPE, NOTIFICATION_CREATED
from app.models import Notification
from app.notifications.validators import check_rate_limiting
from app.schema_validation import validate
from app.v2.notifications.notification_schemas import post_messagebox_request, post_messagebox_response
from tests.app.db import create_api_key, create_service


@pytest.mark.parametrize("reference", [None, "reference_from_client"])
def test_post_messagebox_notification_returns_201(api_client_request, sample_template_with_placeholders, reference):
    data = {
        "reference": ""
    }

    if reference:
        data.update({"reference": reference})

    assert validate(data, post_messagebox_request)

    resp_json = api_client_request.post(
        sample_template_with_placeholders.service_id,
        "v2_notifications.post_notification_messagebox",
        notification_type=MESSAGEBOX_TYPE,
        _data=data
    )

    assert validate(resp_json, post_messagebox_response) == resp_json

    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].status == NOTIFICATION_CREATED
    notification_id = notifications[0].id
    assert resp_json["id"] == str(notification_id)
    assert resp_json["organisation_id"] is None
    assert f"v2/notifications/{notification_id}" in resp_json["uri"]


def test_service_messagebox_permissions(sample_service_full_permissions):
    service = sample_service_full_permissions

    assert service.has_permission(MESSAGEBOX_TYPE)


def test_service_messagebox_rate_limiting(mocker):
    mock_rate_limit = mocker.patch("app.notifications.validators.check_service_over_api_rate_limit")
    mock_daily_limit = mocker.patch("app.notifications.validators.check_service_over_daily_message_limit")
    service = create_service()
    api_key = create_api_key(service=service)

    check_rate_limiting(service, api_key, notification_type=MESSAGEBOX_TYPE)

    mock_rate_limit.assert_called_once_with(service, api_key.key_type)
    assert mock_daily_limit.call_args_list == [
        mocker.call(service, api_key.key_type, notification_type=MESSAGEBOX_TYPE),
    ]
