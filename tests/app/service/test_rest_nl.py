import json
from datetime import datetime

import pytest
from flask import url_for
from freezegun import freeze_time

from app.letters_nl.constants import LETTER_PROVIDER_REST_ENDPOINT
from app.models import Service
from tests import create_admin_authorization_header
from tests.app.db import create_notification, create_organisation, create_service
from tests.app.db_nl import create_organisation_letter_provider
from tests.conftest import set_config


def test_service_letter_address_placement_defaults_to_60mm(sample_service):
    assert sample_service.letter_address_placement == "60mm"


@pytest.mark.parametrize("letter_address_placement", ["50mm", "60mm"])
def test_update_service_letter_address_placement(client, sample_service, letter_address_placement):
    data = {"letter_address_placement": letter_address_placement}

    auth_header = create_admin_authorization_header()

    resp = client.post(
        f"/service/{sample_service.id}",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    result = resp.json
    assert resp.status_code == 200
    assert result["data"]["letter_address_placement"] == letter_address_placement


def test_cant_update_service_letter_address_placement_to_invalid_value(client, sample_service):
    data = {"letter_address_placement": "70mm"}

    auth_header = create_admin_authorization_header()

    resp = client.post(
        f"/service/{sample_service.id}",
        data=json.dumps(data),
        headers=[("Content-Type", "application/json"), auth_header],
    )
    assert resp.status_code == 400
    assert resp.json["message"] == {"letter_address_placement": ["letter_address_placement must be '50mm' or '60mm'"]}


def test_create_pdf_letter(mocker, sample_service_full_permissions, client, fake_uuid, notify_user):
    mocker.patch("app.service.send_notification.utils_s3download")
    mocker.patch("app.service.send_notification.get_page_count", return_value=1)
    mocker.patch("app.service.send_notification.move_uploaded_pdf_to_letters_bucket")

    user = sample_service_full_permissions.users[0]
    data = json.dumps(
        {
            "filename": "valid.pdf",
            "created_by": str(user.id),
            "file_id": fake_uuid,
            "postage": "netherlands",
            "recipient_address": "User%20Name%0AStreet%20Name%20and%20Number%201%0A1234%20PC%20Looney%20Town",
        }
    )

    response = client.post(
        url_for("service.create_pdf_letter", service_id=sample_service_full_permissions.id),
        data=data,
        headers=[("Content-Type", "application/json"), create_admin_authorization_header()],
    )
    json_resp = json.loads(response.get_data(as_text=True))

    assert response.status_code == 201
    assert json_resp == {"id": fake_uuid}


@pytest.mark.parametrize(
    "post_data, expected_errors",
    [
        (
            {},
            [
                {"error": "ValidationError", "message": "postage is a required property"},
                {"error": "ValidationError", "message": "filename is a required property"},
                {"error": "ValidationError", "message": "created_by is a required property"},
                {"error": "ValidationError", "message": "file_id is a required property"},
                {"error": "ValidationError", "message": "recipient_address is a required property"},
            ],
        ),
        (
            {
                "postage": "third",
                "filename": "string",
                "created_by": "string",
                "file_id": "string",
                "recipient_address": "Some Address",
            },
            [
                {
                    "error": "ValidationError",
                    "message": "postage invalid. It must be netherlands, europe or rest-of-world",
                }
            ],
        ),
    ],
)
def test_create_pdf_letter_validates_against_json_schema(
    sample_service_full_permissions, client, post_data, expected_errors
):
    response = client.post(
        url_for("service.create_pdf_letter", service_id=sample_service_full_permissions.id),
        data=json.dumps(post_data),
        headers=[("Content-Type", "application/json"), create_admin_authorization_header()],
    )
    json_resp = json.loads(response.get_data(as_text=True))

    assert response.status_code == 400
    assert json_resp["errors"] == expected_errors


@freeze_time("2018-07-07 16:00:00")
def test_cancel_notification_for_service_refuses_letter_handed_to_provider_after_check(
    admin_request, sample_letter_notification, mocker
):
    # the letter passed the cancellable check, but was claimed for sending before the update ran
    mocker.patch("app.service.rest.letter_can_be_cancelled", return_value=True)
    mock_adjust_redis = mocker.patch("app.service.rest.adjust_daily_service_limits_for_cancelled_letters")
    sample_letter_notification.status = "sending"
    sample_letter_notification.created_at = datetime.now()

    response = admin_request.post(
        "service.cancel_notification_for_service",
        service_id=sample_letter_notification.service_id,
        notification_id=sample_letter_notification.id,
        _expected_status=400,
    )

    assert response["message"] == "We could not cancel this letter. It has already been sent to the print provider."
    assert sample_letter_notification.status == "sending"
    assert not mock_adjust_redis.called


@pytest.fixture
def service_with_rest_endpoint_provider(notify_db_session):
    organisation = create_organisation()
    create_organisation_letter_provider(
        organisation,
        LETTER_PROVIDER_REST_ENDPOINT,
        endpoint_url="https://print.example.com/letters",
        auth_method="api_key",
        auth_config={"api_key_header": "X-Api-Key", "api_key": "super-secret-key"},
        address_placement="50mm",
    )
    service = create_service(organisation=organisation, service_name="placement service")
    service.letter_address_placement = "60mm"
    return service


@pytest.mark.parametrize("delivery_via_providers, expected", [(False, "60mm"), (True, "50mm")])
def test_service_json_has_the_letter_address_placement_its_print_provider_decides(
    notify_api, admin_request, service_with_rest_endpoint_provider, delivery_via_providers, expected
):
    with set_config(notify_api, "LETTER_DELIVERY_VIA_PROVIDERS", delivery_via_providers):
        response = admin_request.get("service.get_service_by_id", service_id=service_with_rest_endpoint_provider.id)

    assert response["data"]["letter_address_placement"] == expected


def test_letter_address_placement_decided_by_print_provider_is_not_written_back(
    notify_api, admin_request, service_with_rest_endpoint_provider
):
    with set_config(notify_api, "LETTER_DELIVERY_VIA_PROVIDERS", True):
        response = admin_request.post(
            "service.update_service",
            service_id=service_with_rest_endpoint_provider.id,
            _data={"name": "renamed service", "letter_address_placement": "50mm"},
        )

    assert response["data"]["name"] == "renamed service"
    assert response["data"]["letter_address_placement"] == "50mm"
    service = Service.query.get(service_with_rest_endpoint_provider.id)
    assert service.name == "renamed service"
    assert service.letter_address_placement == "60mm"


@pytest.mark.parametrize("send_client_reference", [True, False])
def test_update_service_send_client_reference_to_letter_provider(admin_request, sample_service, send_client_reference):
    sample_service.send_client_reference_to_letter_provider = not send_client_reference

    response = admin_request.post(
        "service.update_service",
        service_id=sample_service.id,
        _data={"send_client_reference_to_letter_provider": send_client_reference},
    )

    assert response["data"]["send_client_reference_to_letter_provider"] is send_client_reference
    assert sample_service.send_client_reference_to_letter_provider is send_client_reference


@pytest.mark.parametrize("sent_by, expected", [("pingen", "pingen"), ("dvla", None)])
def test_get_notification_for_service_has_the_print_provider(admin_request, sample_letter_template, sent_by, expected):
    notification = create_notification(template=sample_letter_template, status="sent", sent_by=sent_by)

    response = admin_request.get(
        "service.get_notification_for_service",
        service_id=notification.service_id,
        notification_id=notification.id,
    )

    assert response["status"] == "sent"
    assert response["print_provider"] == expected
