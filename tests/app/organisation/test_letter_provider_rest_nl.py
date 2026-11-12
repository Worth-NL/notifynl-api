import json
import socket
import uuid

import pytest

from app import encryption
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


CONNECTION_TEST = "organisation_letter_provider.start_letter_provider_connection_test"
CONNECTION_TEST_RESULT = "organisation_letter_provider.get_letter_provider_connection_test"
TYPED_API_KEY = {"api_key_header": "X-Api-Key", "api_key": "typed-key"}


@pytest.fixture
def queue_connection_test(mocker):
    mocker.patch("app.organisation.letter_provider_rest_nl.redis_store.active", True)
    mocker.patch("app.letters_nl.letter_endpoint_connection.redis_store.set")
    mocker.patch("app.organisation.letter_provider_rest_nl.redis_store.exceeded_rate_limit", return_value=False)
    return mocker.patch("app.organisation.letter_provider_rest_nl.check_letter_endpoint_connection.apply_async")


def _queued_settings(queue_connection_test):
    return json.loads(encryption.decrypt(queue_connection_test.call_args.args[0][2]))


def test_connection_test_queues_the_typed_values_without_saving_them(
    admin_request, notify_db_session, public_dns, queue_connection_test
):
    organisation = create_organisation()

    response = admin_request.post(
        CONNECTION_TEST,
        organisation_id=organisation.id,
        _data={"endpoint_url": ENDPOINT_URL, "auth_method": "api_key", "auth_config": TYPED_API_KEY},
        _expected_status=201,
    )

    (organisation_id, test_id, encrypted_settings), kwargs = (
        queue_connection_test.call_args.args[0],
        queue_connection_test.call_args.kwargs,
    )
    assert response == {"data": {"id": test_id}}
    assert organisation_id == str(organisation.id)
    assert "typed-key" not in encrypted_settings
    assert _queued_settings(queue_connection_test) == {
        "endpoint_url": ENDPOINT_URL,
        "auth_method": "api_key",
        "auth_config": TYPED_API_KEY,
    }
    assert kwargs == {"queue": "send-letter-tasks", "MessageGroupId": str(organisation.id)}
    stored = dao_get_organisation_letter_provider(organisation.id)
    assert stored.provider.identifier == LETTER_PROVIDER_PINGEN
    assert stored.endpoint_url is None


def test_connection_test_uses_a_stored_secret_left_out_for_the_same_destination(
    admin_request, notify_db_session, public_dns, queue_connection_test
):
    organisation = create_organisation()
    create_organisation_letter_provider(
        organisation,
        LETTER_PROVIDER_REST_ENDPOINT,
        endpoint_url=ENDPOINT_URL,
        auth_method="basic",
        auth_config={"username": "stored", "password": "stored-password"},
        address_placement="50mm",
    )

    admin_request.post(
        CONNECTION_TEST,
        organisation_id=organisation.id,
        _data={"endpoint_url": ENDPOINT_URL, "auth_method": "basic", "auth_config": {"username": "typed"}},
        _expected_status=201,
    )

    assert _queued_settings(queue_connection_test)["auth_config"] == {
        "username": "typed",
        "password": "stored-password",
    }


def test_connection_test_never_sends_a_stored_secret_to_another_url(
    admin_request, notify_db_session, public_dns, queue_connection_test
):
    organisation = create_organisation()
    create_organisation_letter_provider(
        organisation,
        LETTER_PROVIDER_REST_ENDPOINT,
        endpoint_url=ENDPOINT_URL,
        auth_method="basic",
        auth_config={"username": "stored", "password": "stored-password"},
        address_placement="50mm",
    )

    response = admin_request.post(
        CONNECTION_TEST,
        organisation_id=organisation.id,
        _data={
            "endpoint_url": "https://attacker.example.com/letters",
            "auth_method": "basic",
            "auth_config": {"username": "stored"},
        },
        _expected_status=400,
    )

    assert "credentials have to be entered again" in response["message"]
    assert not queue_connection_test.called


def test_connection_test_refuses_an_internal_address(
    admin_request, notify_db_session, public_dns, queue_connection_test
):
    public_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
    organisation = create_organisation()

    response = admin_request.post(
        CONNECTION_TEST,
        organisation_id=organisation.id,
        _data={"endpoint_url": ENDPOINT_URL, "auth_method": "api_key", "auth_config": TYPED_API_KEY},
        _expected_status=400,
    )

    assert "private or internal address" in response["message"]
    assert not queue_connection_test.called


@pytest.mark.parametrize(
    "data",
    [
        {"auth_method": "api_key"},
        {"endpoint_url": ENDPOINT_URL},
        {"endpoint_url": ENDPOINT_URL, "auth_method": "unknown"},
        {"endpoint_url": ENDPOINT_URL, "auth_method": "api_key", "updated_by_id": "nope"},
    ],
)
def test_connection_test_validates_its_input(admin_request, notify_db_session, queue_connection_test, data):
    admin_request.post(CONNECTION_TEST, organisation_id=create_organisation().id, _data=data, _expected_status=400)

    assert not queue_connection_test.called


def test_connection_test_for_an_unknown_organisation(admin_request, notify_db_session, queue_connection_test):
    admin_request.post(
        CONNECTION_TEST,
        organisation_id=uuid.uuid4(),
        _data={"endpoint_url": ENDPOINT_URL, "auth_method": "api_key", "auth_config": TYPED_API_KEY},
        _expected_status=404,
    )

    assert not queue_connection_test.called


def test_connection_test_is_rate_limited_per_organisation(
    admin_request, notify_db_session, public_dns, queue_connection_test, mocker
):
    exceeded = mocker.patch(
        "app.organisation.letter_provider_rest_nl.redis_store.exceeded_rate_limit", return_value=True
    )
    organisation = create_organisation()

    admin_request.post(
        CONNECTION_TEST,
        organisation_id=organisation.id,
        _data={"endpoint_url": ENDPOINT_URL, "auth_method": "api_key", "auth_config": TYPED_API_KEY},
        _expected_status=429,
    )

    exceeded.assert_called_once_with(f"letter-endpoint-connection-test-limit-{organisation.id}", 20, 3600)
    assert not queue_connection_test.called


def test_connection_test_is_refused_without_redis_to_keep_the_result(
    admin_request, notify_db_session, public_dns, queue_connection_test, mocker
):
    mocker.patch("app.organisation.letter_provider_rest_nl.redis_store.active", False)

    admin_request.post(
        CONNECTION_TEST,
        organisation_id=create_organisation().id,
        _data={"endpoint_url": ENDPOINT_URL, "auth_method": "api_key", "auth_config": TYPED_API_KEY},
        _expected_status=503,
    )

    assert not queue_connection_test.called


def test_get_connection_test_result(admin_request, notify_db_session, mocker):
    result = {"state": "finished", "outcome": "authorized"}
    get_result = mocker.patch(
        "app.organisation.letter_provider_rest_nl.get_connection_test_result", return_value=result
    )
    organisation_id, test_id = uuid.uuid4(), uuid.uuid4()

    response = admin_request.get(CONNECTION_TEST_RESULT, organisation_id=organisation_id, test_id=test_id)

    assert response == {"data": result}
    get_result.assert_called_once_with(organisation_id, test_id)


def test_get_connection_test_result_that_expired(admin_request, notify_db_session, mocker):
    mocker.patch("app.organisation.letter_provider_rest_nl.get_connection_test_result", return_value=None)

    admin_request.get(CONNECTION_TEST_RESULT, organisation_id=uuid.uuid4(), test_id=uuid.uuid4(), _expected_status=404)
