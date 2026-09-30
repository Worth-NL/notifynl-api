import socket
import uuid

import pytest

from app.dao.organisation_letter_provider_dao import dao_get_organisation_letter_provider
from app.letters_nl.constants import LETTER_PROVIDER_PINGEN, LETTER_PROVIDER_REST_ENDPOINT
from tests.app.db import create_organisation, create_service
from tests.app.db_nl import create_organisation_letter_provider, delete_organisation_letter_provider

ENDPOINT_URL = "https://print.example.com/letters"


@pytest.fixture
def public_dns(mocker):
    return mocker.patch(
        "app.letters_nl.url_validation.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )


@pytest.fixture
def mock_redis_delete(mocker):
    return mocker.patch("app.dao.organisation_letter_provider_dao.redis_store.delete")


def _set_letter_provider(admin_request, organisation_id, data, _expected_status=200):
    return admin_request.post(
        "organisation_letter_provider.set_organisation_letter_provider",
        organisation_id=organisation_id,
        _data=data,
        _expected_status=_expected_status,
    )


def _rest_endpoint(user, auth_method="api_key", auth_config=None, **overrides):
    return {
        "provider": LETTER_PROVIDER_REST_ENDPOINT,
        "endpoint_url": ENDPOINT_URL,
        "auth_method": auth_method,
        "auth_config": {"api_key": "secret-key"} if auth_config is None else auth_config,
        "address_placement": "50mm",
        "updated_by_id": str(user.id),
    } | overrides


def test_get_organisation_letter_provider_of_new_organisation(admin_request, notify_db_session):
    organisation = create_organisation()

    response = admin_request.get(
        "organisation_letter_provider.get_organisation_letter_provider", organisation_id=organisation.id
    )

    assert response["data"]["identifier"] == LETTER_PROVIDER_PINGEN
    assert response["data"]["address_placement"] == "60mm"


def test_get_organisation_letter_provider_when_none_is_set(admin_request, notify_db_session):
    organisation = create_organisation()
    delete_organisation_letter_provider(organisation)

    response = admin_request.get(
        "organisation_letter_provider.get_organisation_letter_provider", organisation_id=organisation.id
    )

    assert response == {"data": None}


def test_get_organisation_letter_provider_never_returns_secrets(admin_request, notify_db_session):
    organisation = create_organisation()
    create_organisation_letter_provider(
        organisation,
        LETTER_PROVIDER_REST_ENDPOINT,
        endpoint_url=ENDPOINT_URL,
        auth_method="basic",
        auth_config={"username": "denhaag", "password": "hunter2"},
        address_placement="50mm",
    )

    response = admin_request.get(
        "organisation_letter_provider.get_organisation_letter_provider", organisation_id=organisation.id
    )

    assert response["data"]["identifier"] == LETTER_PROVIDER_REST_ENDPOINT
    assert response["data"]["auth_config"] == {"username": "denhaag"}
    assert response["data"]["has_credentials"] is True
    assert "hunter2" not in str(response)


def test_get_organisation_letter_provider_for_unknown_organisation(admin_request, notify_db_session):
    admin_request.get(
        "organisation_letter_provider.get_organisation_letter_provider",
        organisation_id=uuid.uuid4(),
        _expected_status=404,
    )


def test_set_pingen_letter_provider(admin_request, notify_db_session, notify_user, mock_redis_delete):
    organisation = create_organisation()
    service = create_service(organisation=organisation)

    response = _set_letter_provider(
        admin_request,
        organisation.id,
        {"provider": LETTER_PROVIDER_PINGEN, "address_placement": "50mm", "updated_by_id": str(notify_user.id)},
    )

    assert response["data"]["identifier"] == LETTER_PROVIDER_PINGEN
    # Pingen's envelopes fix the address placement
    assert response["data"]["address_placement"] == "60mm"
    assert response["data"]["endpoint_url"] is None
    assert response["data"]["updated_by_id"] == str(notify_user.id)
    mock_redis_delete.assert_any_call(f"organisation-{organisation.id}")
    mock_redis_delete.assert_any_call(f"service-{service.id}")


def test_set_rest_endpoint_letter_provider(admin_request, notify_db_session, notify_user, public_dns):
    organisation = create_organisation()

    response = _set_letter_provider(admin_request, organisation.id, _rest_endpoint(notify_user))

    assert response["data"] | {"updated_at": None} == {
        "organisation_id": str(organisation.id),
        "identifier": LETTER_PROVIDER_REST_ENDPOINT,
        "display_name": "REST-endpoint",
        "endpoint_url": ENDPOINT_URL,
        "auth_method": "api_key",
        "address_placement": "50mm",
        "has_credentials": True,
        # the API key header defaults to X-Api-Key
        "auth_config": {"api_key_header": "X-Api-Key"},
        "is_complete": True,
        "updated_at": None,
        "updated_by_id": str(notify_user.id),
    }
    assert dao_get_organisation_letter_provider(organisation.id).auth_config == {
        "api_key_header": "X-Api-Key",
        "api_key": "secret-key",
    }


def test_updating_rest_endpoint_keeps_secrets_that_are_left_out(
    admin_request, notify_db_session, notify_user, public_dns
):
    organisation = create_organisation()
    _set_letter_provider(
        admin_request,
        organisation.id,
        _rest_endpoint(notify_user, auth_config={"api_key_header": "Authorization", "api_key": "secret-key"}),
    )

    _set_letter_provider(
        admin_request,
        organisation.id,
        _rest_endpoint(notify_user, auth_config={"api_key_header": "X-Other", "api_key": ""}, address_placement="60mm"),
    )

    letter_provider = dao_get_organisation_letter_provider(organisation.id)
    assert letter_provider.address_placement == "60mm"
    assert letter_provider.auth_config == {"api_key_header": "X-Other", "api_key": "secret-key"}


@pytest.mark.parametrize(
    "auth_method, auth_config, secret",
    [
        ("api_key", {"api_key": "secret-key"}, "api_key"),
        ("basic", {"username": "denhaag", "password": "hunter2"}, "password"),
        (
            "oauth",
            {"token_endpoint": "https://idp.example.com/token", "client_id": "notify", "client_secret": "s3cret"},
            "client_secret",
        ),
    ],
)
def test_changing_the_endpoint_url_requires_the_secrets_again(
    admin_request, notify_db_session, notify_user, public_dns, auth_method, auth_config, secret
):
    organisation = create_organisation()
    _set_letter_provider(
        admin_request, organisation.id, _rest_endpoint(notify_user, auth_method=auth_method, auth_config=auth_config)
    )
    elsewhere = "https://attacker.example.net/letters"
    without_secret = {field: value for field, value in auth_config.items() if field != secret}

    response = _set_letter_provider(
        admin_request,
        organisation.id,
        _rest_endpoint(notify_user, auth_method=auth_method, auth_config=without_secret, endpoint_url=elsewhere),
        _expected_status=400,
    )

    assert response["message"] == (
        f"Missing {secret} for auth method {auth_method}: credentials have to be entered again when a URL changes"
    )
    letter_provider = dao_get_organisation_letter_provider(organisation.id)
    assert (letter_provider.endpoint_url, letter_provider.auth_config[secret]) == (ENDPOINT_URL, auth_config[secret])

    _set_letter_provider(
        admin_request,
        organisation.id,
        _rest_endpoint(
            notify_user,
            auth_method=auth_method,
            auth_config=without_secret | {secret: "entered-again"},
            endpoint_url=elsewhere,
        ),
    )

    letter_provider = dao_get_organisation_letter_provider(organisation.id)
    assert (letter_provider.endpoint_url, letter_provider.auth_config[secret]) == (elsewhere, "entered-again")


def test_changing_the_oauth_token_endpoint_requires_the_client_secret_again(
    admin_request, notify_db_session, notify_user, public_dns
):
    organisation = create_organisation()
    auth_config = {"token_endpoint": "https://idp.example.com/token", "client_id": "notify", "client_secret": "s3cret"}
    _set_letter_provider(
        admin_request, organisation.id, _rest_endpoint(notify_user, auth_method="oauth", auth_config=auth_config)
    )

    response = _set_letter_provider(
        admin_request,
        organisation.id,
        _rest_endpoint(
            notify_user,
            auth_method="oauth",
            auth_config={"token_endpoint": "https://attacker.example.net/token", "client_id": "notify"},
        ),
        _expected_status=400,
    )

    assert response["message"] == (
        "Missing client_secret for auth method oauth: credentials have to be entered again when a URL changes"
    )
    assert dao_get_organisation_letter_provider(organisation.id).auth_config == auth_config


def test_changing_auth_method_drops_the_previous_credentials(admin_request, notify_db_session, notify_user, public_dns):
    organisation = create_organisation()
    _set_letter_provider(admin_request, organisation.id, _rest_endpoint(notify_user))

    response = _set_letter_provider(
        admin_request,
        organisation.id,
        _rest_endpoint(notify_user, auth_method="basic", auth_config={"username": "denhaag"}),
        _expected_status=400,
    )

    assert response["message"] == "Missing password for auth method basic"
    assert dao_get_organisation_letter_provider(organisation.id).auth_method == "api_key"


def test_switching_to_pingen_removes_rest_endpoint_credentials(
    admin_request, notify_db_session, notify_user, public_dns
):
    organisation = create_organisation()
    _set_letter_provider(admin_request, organisation.id, _rest_endpoint(notify_user))

    _set_letter_provider(
        admin_request, organisation.id, {"provider": LETTER_PROVIDER_PINGEN, "updated_by_id": str(notify_user.id)}
    )

    letter_provider = dao_get_organisation_letter_provider(organisation.id)
    assert letter_provider.provider.identifier == LETTER_PROVIDER_PINGEN
    assert letter_provider.endpoint_url is None
    assert letter_provider.auth_method is None
    assert letter_provider._auth_config is None


@pytest.mark.parametrize(
    "auth_method, auth_config, missing",
    [
        ("api_key", {}, "api_key"),
        ("basic", {"password": "pass"}, "username"),
        ("oauth", {"token_endpoint": "https://idp.example.com/token", "client_id": "id"}, "client_secret"),
    ],
)
def test_set_rest_endpoint_requires_the_auth_method_credentials(
    admin_request, notify_db_session, notify_user, public_dns, auth_method, auth_config, missing
):
    organisation = create_organisation()

    response = _set_letter_provider(
        admin_request,
        organisation.id,
        _rest_endpoint(notify_user, auth_method=auth_method, auth_config=auth_config),
        _expected_status=400,
    )

    assert response["message"] == f"Missing {missing} for auth method {auth_method}"
    assert dao_get_organisation_letter_provider(organisation.id).provider.identifier == LETTER_PROVIDER_PINGEN


def test_set_rest_endpoint_rejects_private_endpoint(admin_request, notify_db_session, notify_user, mocker):
    mocker.patch(
        "app.letters_nl.url_validation.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.3.7", 443))],
    )
    organisation = create_organisation()

    response = _set_letter_provider(admin_request, organisation.id, _rest_endpoint(notify_user), _expected_status=400)

    assert response["message"] == f"{ENDPOINT_URL} must not point to a private or internal address"
    assert dao_get_organisation_letter_provider(organisation.id).provider.identifier == LETTER_PROVIDER_PINGEN


def test_set_rest_endpoint_validates_the_oauth_token_endpoint(admin_request, notify_db_session, notify_user, mocker):
    def getaddrinfo(host, *args, **kwargs):
        address = "169.254.169.254" if host == "metadata.internal" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    mocker.patch("app.letters_nl.url_validation.socket.getaddrinfo", side_effect=getaddrinfo)
    organisation = create_organisation()

    response = _set_letter_provider(
        admin_request,
        organisation.id,
        _rest_endpoint(
            notify_user,
            auth_method="oauth",
            auth_config={
                "token_endpoint": "https://metadata.internal/token",
                "client_id": "id",
                "client_secret": "secret",
            },
        ),
        _expected_status=400,
    )

    assert "https://metadata.internal/token must not point to a private or internal address" == response["message"]


@pytest.mark.parametrize(
    "data",
    [
        {"provider": "dvla"},
        {"provider": LETTER_PROVIDER_REST_ENDPOINT, "auth_method": "api_key", "address_placement": "50mm"},
        {"provider": LETTER_PROVIDER_REST_ENDPOINT, "endpoint_url": ENDPOINT_URL, "address_placement": "50mm"},
        {"provider": LETTER_PROVIDER_PINGEN, "auth_config": {"unknown": "field"}},
    ],
)
def test_set_letter_provider_validates_the_request(admin_request, notify_db_session, notify_user, data):
    organisation = create_organisation()

    _set_letter_provider(
        admin_request, organisation.id, data | {"updated_by_id": str(notify_user.id)}, _expected_status=400
    )


def test_delete_organisation_letter_provider(admin_request, notify_db_session, mock_redis_delete):
    organisation = create_organisation()
    create_organisation_letter_provider(organisation)

    admin_request.delete(
        "organisation_letter_provider.delete_organisation_letter_provider", organisation_id=organisation.id
    )

    assert dao_get_organisation_letter_provider(organisation.id) is None
    mock_redis_delete.assert_any_call(f"organisation-{organisation.id}")


@pytest.mark.parametrize("header", ["X-Api-Key", "Authorization", "Ocp-Apim-Subscription-Key"])
def test_set_rest_endpoint_accepts_api_key_headers(admin_request, notify_db_session, notify_user, public_dns, header):
    organisation = create_organisation()

    _set_letter_provider(
        admin_request,
        organisation.id,
        _rest_endpoint(notify_user, auth_config={"api_key_header": header, "api_key": "secret-key"}),
    )

    assert dao_get_organisation_letter_provider(organisation.id).auth_config["api_key_header"] == header


@pytest.mark.parametrize("header", ["X Api Key", "X-Api-Key\r\nX-Injected: 1", "Host", "content-length", "X" * 101])
def test_set_rest_endpoint_rejects_unusable_api_key_headers(
    admin_request, notify_db_session, notify_user, public_dns, header
):
    organisation = create_organisation()

    response = _set_letter_provider(
        admin_request,
        organisation.id,
        _rest_endpoint(notify_user, auth_config={"api_key_header": header, "api_key": "secret-key"}),
        _expected_status=400,
    )

    assert response["message"] == f"{header} can't be used as the API key header"
    assert dao_get_organisation_letter_provider(organisation.id).provider.identifier == LETTER_PROVIDER_PINGEN
