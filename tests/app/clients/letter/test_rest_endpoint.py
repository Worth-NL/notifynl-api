import base64
import socket

import pytest
import requests

from app.clients.letter import LetterClientNonRetryableException, LetterClientRetryableException
from app.clients.letter.rest_endpoint import RestEndpointLetterClient
from app.models_nl import OrganisationLetterProvider
from tests.conftest import set_config

ENDPOINT_URL = "https://print.example.com/letters"
TOKEN_URL = "https://idp.example.com/token"


@pytest.fixture
def client(notify_api, statsd_client, public_dns):
    return RestEndpointLetterClient(notify_api, statsd_client)


def _letter_provider(auth_method="api_key", auth_config=None, endpoint_url=ENDPOINT_URL):
    letter_provider = OrganisationLetterProvider(endpoint_url=endpoint_url, auth_method=auth_method)
    letter_provider.auth_config = auth_config or {"api_key_header": "X-Api-Key", "api_key": "secret-key"}
    return letter_provider


def test_send_letter_posts_the_letter_to_the_endpoint(client, letter, rmock):
    rmock.post(ENDPOINT_URL, json={"id": "job-123"}, status_code=200)

    result = client.send_letter(letter, _letter_provider())

    assert result.provider_reference == "job-123"
    request = rmock.last_request
    assert request.json() == {
        "filename": f"{letter.notification_id}.pdf",
        "content": base64.b64encode(letter.pdf).decode(),
        "reference": letter.reference,
        "organisationId": letter.organisation_id,
        "notificationId": letter.notification_id,
        "callbackUrl": letter.callback_url,
    }
    assert request.headers["X-Api-Key"] == "secret-key"
    assert request.headers["User-Agent"] == "NotifyNL"
    assert request.headers["Idempotency-Key"] == letter.notification_id
    assert request.timeout == (10, 60)
    assert request.cert is None


@pytest.mark.parametrize("response_body", [{}, {"status": "ok"}, None])
def test_send_letter_without_an_id_in_the_response(client, letter, rmock, response_body):
    if response_body is None:
        rmock.post(ENDPOINT_URL, text="accepted", status_code=202)
    else:
        rmock.post(ENDPOINT_URL, json=response_body, status_code=201)

    assert client.send_letter(letter, _letter_provider()).provider_reference is None


def test_send_letter_with_custom_api_key_header(client, letter, rmock):
    rmock.post(ENDPOINT_URL, json={})

    client.send_letter(letter, _letter_provider(auth_config={"api_key_header": "Authorization", "api_key": "k"}))

    assert rmock.last_request.headers["Authorization"] == "k"


def test_send_letter_with_basic_auth(client, letter, rmock):
    rmock.post(ENDPOINT_URL, json={})

    client.send_letter(letter, _letter_provider("basic", {"username": "denhaag", "password": "p@ss"}))

    assert rmock.last_request.headers["Authorization"] == "Basic " + base64.b64encode(b"denhaag:p@ss").decode()


def test_send_letter_with_oauth_fetches_and_caches_the_token(client, letter, rmock):
    rmock.post(TOKEN_URL, json={"access_token": "token-1", "expires_in": 3600})
    rmock.post(ENDPOINT_URL, json={})
    letter_provider = _letter_provider(
        "oauth", {"token_endpoint": TOKEN_URL, "client_id": "notify", "client_secret": "s3cret", "scope": "print"}
    )

    client.send_letter(letter, letter_provider)
    client.send_letter(letter, letter_provider)

    token_requests = [r for r in rmock.request_history if r.url == TOKEN_URL]
    assert len(token_requests) == 1
    assert dict(p.split("=") for p in token_requests[0].text.split("&")) == {
        "grant_type": "client_credentials",
        "client_id": "notify",
        "client_secret": "s3cret",
        "scope": "print",
    }
    assert rmock.last_request.headers["Authorization"] == "Bearer token-1"


def test_send_letter_with_oauth_refetches_an_expired_token(client, letter, rmock, mocker):
    rmock.post(TOKEN_URL, [{"json": {"access_token": "token-1", "expires_in": 3600}}, {"json": {"access_token": "t2"}}])
    rmock.post(ENDPOINT_URL, json={})
    letter_provider = _letter_provider("oauth", {"token_endpoint": TOKEN_URL, "client_id": "id", "client_secret": "s"})
    monotonic = mocker.patch("app.clients.letter.rest_endpoint.monotonic", return_value=1000.0)

    client.send_letter(letter, letter_provider)
    monotonic.return_value = 1000.0 + 3600
    client.send_letter(letter, letter_provider)

    assert rmock.last_request.headers["Authorization"] == "Bearer t2"


def test_send_letter_with_oauth_drops_a_rejected_token(client, letter, rmock):
    rmock.post(TOKEN_URL, [{"json": {"access_token": "revoked", "expires_in": 3600}}, {"json": {"access_token": "t2"}}])
    rmock.post(ENDPOINT_URL, [{"status_code": 401}, {"json": {}}])
    letter_provider = _letter_provider("oauth", {"token_endpoint": TOKEN_URL, "client_id": "id", "client_secret": "s"})

    with pytest.raises(LetterClientRetryableException, match="rejected the OAuth access token"):
        client.send_letter(letter, letter_provider)
    client.send_letter(letter, letter_provider)

    assert rmock.last_request.headers["Authorization"] == "Bearer t2"


def test_send_letter_with_oauth_token_failure_is_retryable(client, letter, rmock):
    rmock.post(TOKEN_URL, status_code=400, json={"error": "invalid_client"})
    letter_provider = _letter_provider("oauth", {"token_endpoint": TOKEN_URL, "client_id": "id", "client_secret": "s"})

    with pytest.raises(LetterClientRetryableException, match="Could not get an OAuth access token"):
        client.send_letter(letter, letter_provider)


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_send_letter_server_errors_are_retryable(client, letter, rmock, status_code):
    rmock.post(ENDPOINT_URL, status_code=status_code)

    with pytest.raises(LetterClientRetryableException):
        client.send_letter(letter, _letter_provider())


@pytest.mark.parametrize("exception", [requests.ConnectionError, requests.Timeout, requests.exceptions.SSLError])
def test_send_letter_connection_errors_are_retryable(client, letter, rmock, exception):
    rmock.post(ENDPOINT_URL, exc=exception)

    with pytest.raises(LetterClientRetryableException):
        client.send_letter(letter, _letter_provider())


@pytest.mark.parametrize("status_code", [301, 302, 400, 401, 403, 404, 409, 422])
def test_send_letter_client_errors_and_redirects_are_not_retryable(client, letter, rmock, status_code):
    rmock.post(ENDPOINT_URL, status_code=status_code, headers={"Location": "http://169.254.169.254/"})

    with pytest.raises(LetterClientNonRetryableException) as exc_info:
        client.send_letter(letter, _letter_provider())

    assert exc_info.value.detailed_status_code == f"endpoint-http-{status_code}"
    assert len(rmock.request_history) == 1


def test_send_letter_rechecks_the_endpoint_url(client, letter, rmock, mocker):
    mocker.patch(
        "app.letters_nl.url_validation.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))],
    )

    with pytest.raises(LetterClientNonRetryableException) as exc_info:
        client.send_letter(letter, _letter_provider())

    assert exc_info.value.detailed_status_code == "invalid-endpoint-url"
    assert not rmock.called


def test_send_letter_with_undecryptable_credentials(client, letter, rmock):
    letter_provider = _letter_provider()
    letter_provider._auth_config = "not-a-fernet-token"

    with pytest.raises(LetterClientNonRetryableException) as exc_info:
        client.send_letter(letter, letter_provider)

    assert exc_info.value.detailed_status_code == "invalid-credentials"
    assert not rmock.called


def test_send_letter_presents_client_certificate_for_host(client, letter, rmock, notify_api, tmp_path):
    certificate = tmp_path / "print-example-com.pem"
    certificate.write_text("cert and key")
    rmock.post(ENDPOINT_URL, json={})

    with set_config(notify_api, "SSL_CERT_DIR", str(tmp_path)):
        client.send_letter(letter, _letter_provider())

    assert rmock.last_request.cert == str(certificate)
