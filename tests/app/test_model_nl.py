import pytest

from app.letters_nl.constants import LETTER_PROVIDER_PINGEN, LETTER_PROVIDER_REST_ENDPOINT
from tests.app.db import (
    create_notification,
    create_organisation,
)
from tests.app.db_nl import create_organisation_letter_provider


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


def test_organisation_serialize_includes_area_boundary(notify_db_session):
    organisation = create_organisation(name="Gemeente Den Haag")
    organisation.area_boundary = {
        "type": "Polygon",
        "coordinates": [[[4.30, 52.07], [4.32, 52.07], [4.32, 52.09], [4.30, 52.09], [4.30, 52.07]]],
    }

    serialized = organisation.serialize()

    assert serialized["area_boundary"] == organisation.area_boundary


def test_organisation_serialize_area_boundary_defaults_to_none(notify_db_session):
    organisation = create_organisation(name="Gemeente Rotterdam")

    assert organisation.serialize()["area_boundary"] is None


API_KEY_AUTH_CONFIG = {"api_key_header": "X-Api-Key", "api_key": "super-secret-key"}


def test_organisation_letter_provider_auth_config_is_encrypted_at_rest(notify_db_session):
    letter_provider = create_organisation_letter_provider(
        create_organisation(),
        LETTER_PROVIDER_REST_ENDPOINT,
        endpoint_url="https://print.example.com/letters",
        auth_method="api_key",
        auth_config=API_KEY_AUTH_CONFIG,
    )

    assert "super-secret-key" not in letter_provider._auth_config
    assert letter_provider.auth_config == API_KEY_AUTH_CONFIG
    assert letter_provider.has_credentials is True


def test_organisation_letter_provider_without_auth_config(notify_db_session):
    letter_provider = create_organisation_letter_provider(create_organisation())

    assert letter_provider._auth_config is None
    assert letter_provider.auth_config is None
    assert letter_provider.has_credentials is False


@pytest.mark.parametrize(
    "auth_method, auth_config, expected",
    [
        ("basic", {"username": "user", "password": "pass"}, True),
        ("basic", {"username": "user"}, False),
        ("api_key", API_KEY_AUTH_CONFIG, True),
        ("api_key", {"api_key_header": "X-Api-Key", "api_key": ""}, False),
        ("oauth", {"token_endpoint": "https://idp.example.com/token", "client_id": "id", "client_secret": "s"}, True),
        ("oauth", {"token_endpoint": "https://idp.example.com/token", "client_id": "id"}, False),
        ("api_key", None, False),
        (None, API_KEY_AUTH_CONFIG, False),
    ],
)
def test_organisation_letter_provider_is_complete_for_rest_endpoint(
    notify_db_session, auth_method, auth_config, expected
):
    letter_provider = create_organisation_letter_provider(
        create_organisation(),
        LETTER_PROVIDER_REST_ENDPOINT,
        endpoint_url="https://print.example.com/letters",
        auth_method=auth_method,
        auth_config=auth_config,
    )

    assert letter_provider.is_complete() is expected


def test_organisation_letter_provider_rest_endpoint_without_url_is_incomplete(notify_db_session):
    letter_provider = create_organisation_letter_provider(
        create_organisation(), LETTER_PROVIDER_REST_ENDPOINT, auth_method="api_key", auth_config=API_KEY_AUTH_CONFIG
    )

    assert letter_provider.is_complete() is False


def test_organisation_letter_provider_with_undecryptable_auth_config(notify_db_session):
    letter_provider = create_organisation_letter_provider(
        create_organisation(),
        LETTER_PROVIDER_REST_ENDPOINT,
        endpoint_url="https://print.example.com/letters",
        auth_method="api_key",
    )
    letter_provider._auth_config = "not-a-fernet-token"

    assert letter_provider.is_complete() is False
    assert letter_provider.serialize()["auth_config"] == {"api_key_header": None}


def test_organisation_letter_provider_pingen_is_always_complete(notify_db_session):
    assert create_organisation_letter_provider(create_organisation(), LETTER_PROVIDER_PINGEN).is_complete() is True


def test_organisation_letter_provider_serialize_omits_secrets(notify_db_session):
    organisation = create_organisation()
    letter_provider = create_organisation_letter_provider(
        organisation,
        LETTER_PROVIDER_REST_ENDPOINT,
        endpoint_url="https://print.example.com/letters",
        auth_method="oauth",
        auth_config={
            "token_endpoint": "https://idp.example.com/token",
            "client_id": "notify",
            "client_secret": "super-secret",
            "scope": "letters",
        },
        address_placement="50mm",
    )

    serialized = letter_provider.serialize()

    assert serialized == {
        "organisation_id": str(organisation.id),
        "identifier": LETTER_PROVIDER_REST_ENDPOINT,
        "display_name": "REST-endpoint",
        "endpoint_url": "https://print.example.com/letters",
        "auth_method": "oauth",
        "address_placement": "50mm",
        "has_credentials": True,
        "auth_config": {"token_endpoint": "https://idp.example.com/token", "client_id": "notify", "scope": "letters"},
        "is_complete": True,
        "updated_at": None,
        "updated_by_id": None,
    }
    assert "super-secret" not in str(serialized)


def test_organisation_serialize_includes_letter_provider_summary(notify_db_session):
    organisation = create_organisation()
    create_organisation_letter_provider(
        organisation,
        LETTER_PROVIDER_REST_ENDPOINT,
        endpoint_url="https://print.example.com/letters",
        auth_method="api_key",
        auth_config=API_KEY_AUTH_CONFIG,
        address_placement="50mm",
    )

    assert organisation.serialize()["letter_provider"] == {
        "identifier": LETTER_PROVIDER_REST_ENDPOINT,
        "display_name": "REST-endpoint",
        "endpoint_url": "https://print.example.com/letters",
        "auth_method": "api_key",
        "address_placement": "50mm",
        "has_credentials": True,
    }


def test_organisation_serialize_letter_provider_defaults_to_none(notify_db_session):
    assert create_organisation().serialize()["letter_provider"] is None


def test_service_does_not_send_client_reference_to_letter_provider_by_default(sample_service):
    assert sample_service.send_client_reference_to_letter_provider is False
