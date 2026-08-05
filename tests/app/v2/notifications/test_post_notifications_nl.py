"""
NL adaptations of tests from test_post_notifications.py that are skipped there due to Dutch phone
number validation. Phone numbers are replaced with valid Dutch mobile numbers (06xxxxxxxx format).

Tests not included here because they test UK-specific concepts without a direct NL equivalent:
- test_post_sms_notification_returns_400_if_not_allowed_to_send_int_sms (UK error message path differs)
- test_post_sms_notification_returns_201_if_allowed_to_send_to_uk_landlines (UK landlines not applicable)
- test_post_sms_notification_returns_400_if_not_allowed_to_send_to_uk_landlines (UK landlines not applicable)
"""

import json
from unittest.mock import call

import pytest

from app.constants import EMAIL_TYPE
from app.dao import templates_dao
from app.dao.service_sms_sender_dao import dao_update_service_sms_sender
from app.models import Notification
from app.schema_validation import validate
from app.v2.notifications.notification_schemas import post_sms_response
from tests.app.db import (
    create_service_sms_sender,
    create_service_with_inbound_number,
    create_template,
)


def test_post_sms_notification_uses_inbound_number_reply_to_as_sender_nl(api_client_request, notify_db_session, mocker):
    service = create_service_with_inbound_number(inbound_number="0612345678")

    template = create_template(service=service, content="Hello (( Name))\nYour thing is due soon")
    mocked = mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")
    data = {"phone_number": "0687654321", "template_id": str(template.id), "personalisation": {" Name": "Jo"}}

    resp_json = api_client_request.post(
        service.id,
        "v2_notifications.post_notification",
        notification_type="sms",
        _data=data,
    )

    assert validate(resp_json, post_sms_response) == resp_json
    notifications = Notification.query.all()
    assert len(notifications) == 1
    notification_id = notifications[0].id
    assert resp_json["id"] == str(notification_id)
    assert resp_json["content"]["from_number"] == "31612345678"
    assert notifications[0].reply_to_text == "31612345678"
    mocked.assert_called_once_with(
        [str(notification_id)],
        queue="send-sms-tasks",
        MessageGroupId=str(service.id),
    )


def test_post_sms_notification_uses_sms_sender_id_reply_to_nl(
    api_client_request, sample_template_with_placeholders, mocker
):
    sms_sender = create_service_sms_sender(service=sample_template_with_placeholders.service, sms_sender="0612345678")
    mocked = mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")
    data = {
        "phone_number": "0687654321",
        "template_id": str(sample_template_with_placeholders.id),
        "personalisation": {" Name": "Jo"},
        "sms_sender_id": str(sms_sender.id),
    }

    resp_json = api_client_request.post(
        sample_template_with_placeholders.service_id,
        "v2_notifications.post_notification",
        notification_type="sms",
        _data=data,
    )

    assert validate(resp_json, post_sms_response) == resp_json
    assert resp_json["content"]["from_number"] == "31612345678"
    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].reply_to_text == "31612345678"
    mocked.assert_called_once_with(
        [resp_json["id"]],
        queue="send-sms-tasks",
        MessageGroupId=str(sample_template_with_placeholders.service_id),
    )


def test_notification_reply_to_text_is_original_value_if_sender_is_changed_after_post_notification_nl(
    api_client_request, sample_template, mocker
):
    sms_sender = create_service_sms_sender(service=sample_template.service, sms_sender="123456", is_default=False)
    mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")
    data = {
        "phone_number": "0612345678",
        "template_id": str(sample_template.id),
        "sms_sender_id": str(sms_sender.id),
    }

    api_client_request.post(
        sample_template.service_id,
        "v2_notifications.post_notification",
        notification_type="sms",
        _data=data,
    )

    dao_update_service_sms_sender(
        service_id=sample_template.service_id,
        service_sms_sender_id=sms_sender.id,
        is_default=sms_sender.is_default,
        sms_sender="updated",
    )

    notifications = Notification.query.all()
    assert len(notifications) == 1
    assert notifications[0].reply_to_text == "123456"


@pytest.mark.flaky(max_runs=3, min_passes=1)
def test_should_cache_template_lookups_in_memory_nl(mocker, api_client_request, sample_template):
    mock_get_template = mocker.patch(
        "app.dao.templates_dao.dao_get_template_by_id_and_service_id",
        wraps=templates_dao.dao_get_template_by_id_and_service_id,
    )
    mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")

    data = {
        "phone_number": "0612345678",
        "template_id": str(sample_template.id),
    }

    for _ in range(5):
        api_client_request.post(
            sample_template.service_id,
            "v2_notifications.post_notification",
            notification_type="sms",
            _data=data,
        )

    assert mock_get_template.call_count == 1
    assert mock_get_template.call_args_list == [
        call(service_id=str(sample_template.service_id), template_id=str(sample_template.id), version=None)
    ]
    assert Notification.query.count() == 5


def test_should_cache_template_and_service_in_redis_nl(mocker, api_client_request, sample_template):
    from app.schemas import service_schema, template_schema

    mock_redis_get = mocker.patch(
        "app.redis_store.get",
        return_value=None,
    )
    mock_redis_set = mocker.patch(
        "app.redis_store.set",
    )

    mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")

    data = {
        "phone_number": "0612345678",
        "template_id": str(sample_template.id),
    }

    api_client_request.post(
        sample_template.service_id,
        "v2_notifications.post_notification",
        notification_type="sms",
        _data=data,
    )

    expected_service_key = f"service-{sample_template.service_id}"
    expected_templates_key = f"service-{sample_template.service_id}-template-{sample_template.id}-version-None"

    assert mock_redis_get.call_args_list == [
        call(expected_service_key),
        call(expected_templates_key),
    ]

    service_dict = service_schema.dump(sample_template.service)
    template_dict = template_schema.dump(sample_template)

    assert len(mock_redis_set.call_args_list) == 2

    service_call, templates_call = mock_redis_set.call_args_list

    assert service_call[0][0] == expected_service_key
    assert json.loads(service_call[0][1]) == {"data": service_dict}
    assert service_call[1]["ex"] == 2_419_200

    assert templates_call[0][0] == expected_templates_key
    assert json.loads(templates_call[0][1]) == {"data": template_dict}
    assert templates_call[1]["ex"] == 2_419_200


def test_should_return_template_if_found_in_redis_nl(mocker, api_client_request, sample_template):
    from app.schemas import service_schema, template_schema

    service_dict = service_schema.dump(sample_template.service)
    template_dict = template_schema.dump(sample_template)

    mocker.patch(
        "app.redis_store.get",
        side_effect=[
            json.dumps({"data": service_dict}).encode("utf-8"),
            json.dumps({"data": template_dict}).encode("utf-8"),
        ],
    )
    mock_get_template = mocker.patch("app.dao.templates_dao.dao_get_template_by_id_and_service_id")
    mock_get_service = mocker.patch("app.dao.services_dao.dao_fetch_service_by_id")

    mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")

    data = {
        "phone_number": "0612345678",
        "template_id": str(sample_template.id),
    }

    api_client_request.post(
        sample_template.service_id,
        "v2_notifications.post_notification",
        notification_type="sms",
        _data=data,
    )

    assert mock_get_template.called is False
    assert mock_get_service.called is False


@pytest.mark.parametrize(
    "recipient, notification_type",
    [
        ("simulate-delivered@notifications.service.gov.uk", EMAIL_TYPE),
        ("simulate-delivered-2@notifications.service.gov.uk", EMAIL_TYPE),
        ("simulate-delivered-3@notifications.service.gov.uk", EMAIL_TYPE),
        # SMS simulated recipients require NL simulated numbers to be configured in
        # SIMULATED_SMS_NUMBERS (currently set to UK numbers). Pending NL config update.
    ],
)
def test_should_not_persist_or_send_notification_if_simulated_recipient_nl(
    api_client_request, recipient, notification_type, sample_email_template, sample_template, mocker
):
    apply_async = mocker.patch(f"app.celery.provider_tasks.deliver_{notification_type}.apply_async")

    data = {"email_address": recipient, "template_id": str(sample_email_template.id)}

    resp_json = api_client_request.post(
        sample_email_template.service_id,
        "v2_notifications.post_notification",
        notification_type=notification_type,
        _data=data,
    )

    apply_async.assert_not_called()
    assert resp_json["id"]
    assert Notification.query.count() == 0


def test_post_email_notification_response_has_sanitised_content_info_for_sms_nl(
    api_client_request, sample_service, mocker
):
    template = create_template(service=sample_service, template_type="sms")
    mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")

    data = {
        "template_id": template.id,
        "phone_number": "0612345678",
    }

    response = api_client_request.post(
        template.service_id,
        "v2_notifications.post_notification",
        notification_type="sms",
        _data=data,
        _api_key_type="test",
    )

    assert "sanitised_content" not in response


def test_post_email_notification_response_has_sanitised_content_info_for_letter_nl(
    api_client_request, sample_service, mocker
):
    template = create_template(service=sample_service, template_type="letter")
    mocker.patch("app.celery.letters_pdf_tasks.get_pdf_for_templated_letter.apply_async")
    mocker.patch("app.celery.research_mode_tasks.create_fake_letter_callback.apply_async")

    data = {
        "template_id": template.id,
        "personalisation": {
            "address_line_1": "Amala Pidge",
            "address_line_2": "6 Dove St",
            "address_line_3": "1234 AB Amsterdam",
        },
    }

    response = api_client_request.post(
        template.service_id,
        "v2_notifications.post_notification",
        notification_type="letter",
        _data=data,
        _api_key_type="test",
    )

    assert "sanitised_content" not in response
