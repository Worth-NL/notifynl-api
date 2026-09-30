import pytest
import requests

from app.clients.letter import LetterClientNonRetryableException, LetterClientRetryableException
from app.clients.letter.pingen import PingenClient
from tests.conftest import set_config_values

API = "https://api-staging.pingen.com"
IDENTITY = "https://identity-staging.pingen.com"
ORGANISATION_ID = "0f8b0e4c-2d39-4c3f-8c8b-6d1f0d4a1b2c"
LETTERS_URL = f"{API}/organisations/{ORGANISATION_ID}/deliveries/letters"
UPLOAD_URL = "https://pingen-uploads.s3.example.com/upload?X-Amz-Signature=abc"
LETTER_ID = "5c6a1a53-5f8a-4bd1-9d2b-2f3a4b5c6d7e"


@pytest.fixture
def pingen_config(notify_api):
    with set_config_values(
        notify_api,
        {
            "PINGEN_API_URL": API,
            "PINGEN_IDENTITY_URL": IDENTITY,
            "PINGEN_CLIENT_ID": "client-id",
            "PINGEN_CLIENT_SECRET": "client-secret",
            "PINGEN_ORGANISATION_ID": ORGANISATION_ID,
            "PINGEN_DELIVERY_PRODUCT": "cheap",
            "PINGEN_PRINT_MODE": "simplex",
            "PINGEN_PRINT_SPECTRUM": "color",
        },
    ):
        yield


@pytest.fixture
def client(notify_api, statsd_client, pingen_config):
    return PingenClient(notify_api, statsd_client)


@pytest.fixture
def pingen(rmock):
    rmock.post(
        f"{IDENTITY}/auth/access-tokens", json={"token_type": "Bearer", "expires_in": 43200, "access_token": "t"}
    )
    rmock.get(
        f"{API}/file-upload",
        json={
            "data": {
                "id": "a7f0e9d8-c7b6-4a5f-9e8d-7c6b5a4f3e2d",
                "type": "file_uploads",
                "attributes": {"url": UPLOAD_URL, "url_signature": "sig", "expires_at": "2026-09-29T15:00:00+0200"},
            }
        },
    )
    rmock.put(UPLOAD_URL, status_code=200)
    rmock.post(LETTERS_URL, status_code=201, json={"data": {"id": LETTER_ID, "type": "letters", "attributes": {}}})
    return rmock


def _requests(rmock, method, url):
    return [r for r in rmock.request_history if r.method == method and r.url.split("?")[0] == url.split("?")[0]]


def test_send_letter_creates_a_letter_that_pingen_sends_automatically(client, letter, pingen):
    result = client.send_letter(letter, None)

    assert result.provider_reference == LETTER_ID

    (token_request,) = _requests(pingen, "POST", f"{IDENTITY}/auth/access-tokens")
    assert dict(p.split("=") for p in token_request.text.split("&")) == {
        "grant_type": "client_credentials",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "scope": "letter",
    }

    (upload_request,) = _requests(pingen, "PUT", UPLOAD_URL)
    assert upload_request.body == letter.pdf
    assert "Authorization" not in upload_request.headers

    (create_request,) = _requests(pingen, "POST", LETTERS_URL)
    assert create_request.headers["Authorization"] == "Bearer t"
    assert create_request.headers["Content-Type"] == "application/vnd.api+json"
    assert create_request.headers["Idempotency-Key"] == f"notifynl-letter-{letter.notification_id}"
    assert create_request.json() == {
        "data": {
            "type": "letters",
            "attributes": {
                "file_original_name": f"{letter.notification_id}.pdf",
                "file_url": UPLOAD_URL,
                "file_url_signature": "sig",
                "address_position": "left",
                "auto_send": True,
                "delivery_product": "cheap",
                "print_mode": "simplex",
                "print_spectrum": "color",
            },
        }
    }


def test_send_letter_reuses_the_access_token(client, letter, pingen):
    client.send_letter(letter, None)
    client.send_letter(letter, None)

    assert len(_requests(pingen, "POST", f"{IDENTITY}/auth/access-tokens")) == 1


def test_send_letter_refreshes_the_access_token_before_it_expires(client, letter, pingen, mocker):
    monotonic = mocker.patch("app.clients.letter.pingen.monotonic", return_value=1000.0)
    client.send_letter(letter, None)

    monotonic.return_value = 1000.0 + 43200 - 299
    client.send_letter(letter, None)

    assert len(_requests(pingen, "POST", f"{IDENTITY}/auth/access-tokens")) == 2


def test_send_letter_drops_a_rejected_access_token(client, letter, pingen):
    pingen.get(f"{API}/file-upload", [{"status_code": 401}, {"json": pingen_file_upload_response()}])

    with pytest.raises(LetterClientRetryableException, match="rejected the access token"):
        client.send_letter(letter, None)
    client.send_letter(letter, None)

    assert len(_requests(pingen, "POST", f"{IDENTITY}/auth/access-tokens")) == 2


def pingen_file_upload_response():
    return {"data": {"id": "x", "type": "file_uploads", "attributes": {"url": UPLOAD_URL, "url_signature": "sig"}}}


@pytest.mark.parametrize("status_code", [400, 401, 500])
def test_access_token_failures_are_retryable(client, letter, pingen, status_code):
    pingen.post(f"{IDENTITY}/auth/access-tokens", status_code=status_code)

    with pytest.raises(LetterClientRetryableException, match="access token"):
        client.send_letter(letter, None)

    assert not _requests(pingen, "POST", LETTERS_URL)


@pytest.mark.parametrize("status_code", [409, 424, 429, 500, 503])
def test_create_letter_retryable_errors(client, letter, pingen, status_code):
    pingen.post(LETTERS_URL, status_code=status_code)

    with pytest.raises(LetterClientRetryableException):
        client.send_letter(letter, None)


@pytest.mark.parametrize("status_code", [400, 403, 404, 422])
def test_create_letter_rejections_are_not_retryable(client, letter, pingen, status_code):
    pingen.post(
        LETTERS_URL,
        status_code=status_code,
        json={"errors": [{"code": "x", "title": "Invalid", "detail": "file_url_signature is invalid", "source": {}}]},
    )

    with pytest.raises(LetterClientNonRetryableException, match="file_url_signature is invalid") as exc_info:
        client.send_letter(letter, None)

    assert exc_info.value.detailed_status_code == f"pingen-http-{status_code}"


@pytest.mark.parametrize("status_code", [403, 500])
def test_upload_failures_are_retryable(client, letter, pingen, status_code):
    pingen.put(UPLOAD_URL, status_code=status_code)

    with pytest.raises(LetterClientRetryableException, match="Uploading the letter"):
        client.send_letter(letter, None)

    assert not _requests(pingen, "POST", LETTERS_URL)


@pytest.mark.parametrize("exception", [requests.ConnectionError, requests.Timeout])
def test_connection_errors_are_retryable(client, letter, pingen, exception):
    pingen.post(LETTERS_URL, exc=exception)

    with pytest.raises(LetterClientRetryableException):
        client.send_letter(letter, None)


WEBHOOKS_URL = f"{API}/organisations/{ORGANISATION_ID}/webhooks"


def test_webhooks_use_their_own_access_token_scope(client, letter, pingen):
    pingen.get(
        WEBHOOKS_URL,
        json={
            "data": [
                {
                    "id": "b1",
                    "type": "webhooks",
                    "attributes": {"event_category": "sent", "url": "https://x/y", "signing_key": "k" * 20},
                }
            ]
        },
    )
    pingen.post(WEBHOOKS_URL, status_code=201, json={"data": {"id": "b2", "type": "webhooks"}})

    client.send_letter(letter, None)
    assert client.list_webhooks() == [
        {"id": "b1", "event_category": "sent", "url": "https://x/y", "signing_key": "k" * 20}
    ]
    assert client.create_webhook("issues", "https://x/y", "k" * 20) == "b2"

    token_requests = _requests(pingen, "POST", f"{IDENTITY}/auth/access-tokens")
    assert [dict(p.split("=") for p in r.text.split("&"))["scope"] for r in token_requests] == ["letter", "webhook"]
    (create_request,) = _requests(pingen, "POST", WEBHOOKS_URL)
    assert create_request.headers["Content-Type"] == "application/vnd.api+json"
    assert create_request.json() == {
        "data": {
            "type": "webhooks",
            "attributes": {"event_category": "issues", "url": "https://x/y", "signing_key": "k" * 20},
        }
    }
