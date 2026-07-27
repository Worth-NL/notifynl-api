import pytest
from marshmallow import ValidationError
from sqlalchemy import desc

from app import encryption
from app.constants import MESSAGEBOX_TYPE, ServiceCallbackTypes
from app.dao.provider_details_dao import (
    dao_update_provider_details,
    get_provider_details_by_identifier,
)
from app.dao.service_callback_api_dao import save_service_callback_api
from app.dao.templates_messagebox_dao import get_messagebox_template
from app.models import ProviderDetailsHistory, ServiceCallbackApi
from tests.app.db import create_api_key, create_notification, create_service


def test_job_schema_doesnt_return_notifications(sample_notification_with_job):
    from app.schemas import job_schema

    job = sample_notification_with_job.job
    assert job.notifications.count() == 1

    data = job_schema.dump(job)

    assert "notifications" not in data


def test_notification_schema_ignores_absent_api_key(sample_notification_with_job):
    from app.schemas import notification_with_template_schema

    data = notification_with_template_schema.dump(sample_notification_with_job)
    assert data["key_name"] is None


def test_notification_schema_adds_api_key_name(sample_notification):
    from app.schemas import notification_with_template_schema

    api_key = create_api_key(sample_notification.service, key_name="Test key")
    sample_notification.api_key = api_key

    data = notification_with_template_schema.dump(sample_notification)
    assert data["key_name"] == "Test key"


def test_notification_schema_includes_templates_bilingual_related_fields(sample_letter_notification):
    from app.schemas import notification_with_template_schema

    sample_letter_notification.template.letter_languages = "welsh_then_english"
    sample_letter_notification.template.letter_welsh_subject = "Bore da"
    sample_letter_notification.template.letter_welsh_content = "Cymraeg da"

    data = notification_with_template_schema.dump(sample_letter_notification)
    assert data["template"]["letter_languages"] == "welsh_then_english"
    assert data["template"]["letter_welsh_subject"] == "Bore da"
    assert data["template"]["letter_welsh_content"] == "Cymraeg da"


@pytest.mark.parametrize(
    "schema_name",
    [
        "notification_schema",
        "notification_with_template_schema",
    ],
)
def test_notification_schema_has_correct_status(sample_notification, schema_name):
    from app import schemas

    data = getattr(schemas, schema_name).dump(sample_notification)

    assert data["status"] == sample_notification.status


def test_notification_with_template_schema_masks_messagebox_recipient(notify_db_session, notify_user):
    from app.schemas import notification_with_template_schema

    service = create_service(service_permissions=[MESSAGEBOX_TYPE])
    template = get_messagebox_template(service.id)
    notification = create_notification(
        template=template,
        to_field=encryption.encrypt("123456789"),
        normalised_to=None,
        status="delivered",
    )

    data = notification_with_template_schema.dump(notification)

    assert data["to"] == str(notification.id)


def test_notification_with_template_schema_keeps_recipient_for_non_messagebox(sample_notification):
    from app.schemas import notification_with_template_schema

    data = notification_with_template_schema.dump(sample_notification)

    assert data["to"] == sample_notification.to


def test_notification_with_template_schema_adds_messagebox_failure_reason_for_known_code(
    notify_db_session, notify_user
):
    from app.schemas import notification_with_template_schema

    service = create_service(service_permissions=[MESSAGEBOX_TYPE])
    template = get_messagebox_template(service.id)
    notification = create_notification(
        template=template,
        to_field=encryption.encrypt("123456789"),
        normalised_to=None,
        status="permanent-failure",
    )
    notification.detailed_status_code = "OinInCPAKomtNietOvereenMetOinInBericht"

    data = notification_with_template_schema.dump(notification)

    assert data["messagebox_failure_reason"] == "OIN uit CPA komt niet overeen met OID in het bericht"


def test_notification_with_template_schema_messagebox_failure_reason_none_for_unknown_code(
    notify_db_session, notify_user
):
    from app.schemas import notification_with_template_schema

    service = create_service(service_permissions=[MESSAGEBOX_TYPE])
    template = get_messagebox_template(service.id)
    notification = create_notification(
        template=template,
        to_field=encryption.encrypt("123456789"),
        normalised_to=None,
        status="technical-failure",
    )
    notification.detailed_status_code = None

    data = notification_with_template_schema.dump(notification)

    assert data["messagebox_failure_reason"] is None


def test_notification_with_template_schema_messagebox_failure_reason_none_for_non_messagebox(sample_notification):
    from app.schemas import notification_with_template_schema

    data = notification_with_template_schema.dump(sample_notification)

    assert data["messagebox_failure_reason"] is None


@pytest.mark.parametrize(
    "user_attribute, user_value",
    [("name", "New User"), ("email_address", "newuser@mail.com"), ("mobile_number", "+4407700900460")],
)
def test_user_update_schema_accepts_valid_attribute_pairs(user_attribute, user_value):
    update_dict = {user_attribute: user_value}
    from app.schemas import user_update_schema_load_json

    errors = user_update_schema_load_json.validate(update_dict)
    assert not errors


@pytest.mark.parametrize(
    "user_attribute, user_value",
    [("name", None), ("name", ""), ("email_address", "bademail@...com"), ("mobile_number", "06000400200")],
)
def test_user_update_schema_rejects_invalid_attribute_pairs(user_attribute, user_value):
    from app.schemas import user_update_schema_load_json

    update_dict = {user_attribute: user_value}
    with pytest.raises(ValidationError):
        user_update_schema_load_json.load(update_dict)


@pytest.mark.parametrize(
    "user_attribute",
    [
        "id",
        "updated_at",
        "created_at",
        "user_to_service",
        "_password",
        "verify_codes",
        "logged_in_at",
        "password_changed_at",
        "failed_login_count",
        "state",
    ],
)
def test_user_update_schema_rejects_disallowed_attribute_keys(user_attribute):
    update_dict = {user_attribute: "not important"}
    from app.schemas import user_update_schema_load_json

    with pytest.raises(ValidationError) as excinfo:
        user_update_schema_load_json.load(update_dict)

    assert excinfo.value.messages["_schema"][0] == f"Unknown field name {user_attribute}"


def test_provider_details_schema_returns_user_details(mocker, sample_user, restore_provider_details):
    from app.schemas import provider_details_schema

    current_sms_provider = get_provider_details_by_identifier("mmg")
    current_sms_provider.created_by = sample_user
    data = provider_details_schema.dump(current_sms_provider)

    assert sorted(data["created_by"].keys()) == sorted(["id", "email_address", "name"])


def test_provider_details_history_schema_returns_user_details(
    sample_user,
    restore_provider_details,
):
    from app.schemas import provider_details_schema

    current_sms_provider = get_provider_details_by_identifier("mmg")
    current_sms_provider.created_by_id = sample_user.id
    data = provider_details_schema.dump(current_sms_provider)

    dao_update_provider_details(current_sms_provider)

    current_sms_provider_in_history = (
        ProviderDetailsHistory.query.filter(ProviderDetailsHistory.id == current_sms_provider.id)
        .order_by(desc(ProviderDetailsHistory.version))
        .first()
    )
    data = provider_details_schema.dump(current_sms_provider_in_history)

    assert sorted(data["created_by"].keys()) == sorted(["id", "email_address", "name"])


def test_service_schema_only_returns_both_delivery_status_and_returned_letter_callback_api(sample_service):
    from app.schemas import service_schema

    service_delivery_callback_api = ServiceCallbackApi(
        service_id=sample_service.id,
        url="https://some_service/delivery_callback_endpoint",
        bearer_token="delivery_unique_string",
        updated_by_id=sample_service.users[0].id,
        callback_type=ServiceCallbackTypes.delivery_status,
    )
    save_service_callback_api(service_delivery_callback_api)

    service_complaint_callback_api = ServiceCallbackApi(
        service_id=sample_service.id,
        url="https://some_service/complaint_callback_endpoint",
        bearer_token="complaint_unique_string",
        updated_by_id=sample_service.users[0].id,
        callback_type=ServiceCallbackTypes.complaint.value,
    )
    save_service_callback_api(service_complaint_callback_api)

    service_returned_letter_callback_api = ServiceCallbackApi(
        service_id=sample_service.id,
        url="https://some_service/returned_letter_callback_endpoint",
        bearer_token="complaint_unique_string",
        updated_by_id=sample_service.users[0].id,
        callback_type=ServiceCallbackTypes.returned_letter.value,
    )
    save_service_callback_api(service_returned_letter_callback_api)

    data = service_schema.dump(sample_service)

    assert data["service_callback_api"] == [
        {
            "callback_id": str(service_delivery_callback_api.id),
            "callback_type": service_delivery_callback_api.callback_type,
        },
        {
            "callback_id": str(service_complaint_callback_api.id),
            "callback_type": service_complaint_callback_api.callback_type,
        },
        {
            "callback_id": str(service_returned_letter_callback_api.id),
            "callback_type": service_returned_letter_callback_api.callback_type,
        },
    ]


@pytest.mark.parametrize("oin", [None, "", "01234567890123456789"])
def test_service_schema_accepts_blank_or_valid_oin(sample_service, oin):
    from app.schemas import service_schema

    data = dict(service_schema.dump(sample_service))
    data["oin"] = oin

    service = service_schema.load(data, instance=sample_service, partial=True)

    assert service.oin == oin


@pytest.mark.parametrize(
    "oin",
    [
        "1234567890123456789",  # 19 digits
        "123456789012345678901",  # 21 digits
        "abcdefghijklmnopqrst",  # non-digit, 20 chars
    ],
)
def test_service_schema_rejects_invalid_oin(sample_service, oin):
    from app.schemas import service_schema

    data = dict(service_schema.dump(sample_service))
    data["oin"] = oin

    with pytest.raises(ValidationError):
        service_schema.load(data, instance=sample_service, partial=True)
