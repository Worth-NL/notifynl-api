import base64
import json
import socket

import pytest
import requests
from celery.exceptions import SoftTimeLimitExceeded
from pypdf import PdfReader
from redis.exceptions import ConnectionError as RedisConnectionError
from urllib3.exceptions import ProtocolError

from app.letters_nl.letter_endpoint_connection import (
    MAX_BODY_READ,
    MAX_BODY_SHOWN,
    REDACTED,
    TEST_LETTER_PDF,
    create_connection_test,
    encrypt_connection_test_settings,
    get_connection_test_result,
    run_connection_test,
)
from app.models import Notification, NotificationHistory
from app.models_nl import LetterProviderPin, LetterProviderReference
from tests.app.clients.letter.conftest import FAILED_AFTER_SENDING, FAILED_TO_CONNECT

ORGANISATION_ID = "9d0c6c4a-5a5e-4c7a-9f7e-3c2d1b0a9f8e"
CONNECTION_TEST_ID = "7b2dd5d6-b52f-4a9c-9d0e-9d3b4b1b4a51"
ENDPOINT_URL = "https://print.example.com/letters"
TOKEN_URL = "https://idp.example.com/token"
CALLBACK_URL = "https://api.notifynl.nl/notifications/letter/provider-status?token=signed"
API_KEY = {"api_key_header": "X-Api-Key", "api_key": "secret-key"}
OAUTH = {"token_endpoint": TOKEN_URL, "client_id": "client", "client_secret": "client-secret"}


@pytest.fixture(autouse=True)
def public_dns(mocker):
    return mocker.patch(
        "app.letters_nl.url_validation.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )


@pytest.fixture(autouse=True)
def redis_results(notify_api, mocker):
    results = {}
    mocker.patch(
        "app.letters_nl.letter_endpoint_connection.redis_store.set",
        side_effect=lambda key, value, ex=None: results.__setitem__(key, value),
    )
    mocker.patch(
        "app.letters_nl.letter_endpoint_connection.redis_store.get",
        side_effect=lambda key, **kwargs: results.get(key),
    )
    return results


@pytest.fixture(autouse=True)
def queued_test(redis_results, mocker):
    # as the API starts one: a test only runs while admin still waits for its result
    mocker.patch("app.letters_nl.letter_endpoint_connection.uuid4", return_value=CONNECTION_TEST_ID)
    create_connection_test(ORGANISATION_ID)


def _run(auth_method="api_key", auth_config=None, endpoint_url=ENDPOINT_URL):
    run_connection_test(
        ORGANISATION_ID,
        CONNECTION_TEST_ID,
        encrypt_connection_test_settings(endpoint_url, auth_method, auth_config or API_KEY),
        CALLBACK_URL,
    )
    return get_connection_test_result(ORGANISATION_ID, CONNECTION_TEST_ID)


def test_the_test_letter_is_one_a4_page_without_an_address():
    reader = PdfReader(TEST_LETTER_PDF, strict=True)

    assert len(reader.pages) == 1
    assert (round(reader.pages[0].mediabox.width), round(reader.pages[0].mediabox.height)) == (595, 842)
    assert reader.pages[0].extract_text() == "NotifyNL verbindingstest, niet afdrukken"


def test_the_letter_is_sent_like_a_real_letter_but_with_the_test_id_and_a_shorter_timeout(rmock):
    rmock.post(ENDPOINT_URL, json={"id": "job-123"})

    _run()

    request = rmock.last_request
    assert request.json() == {
        "filename": f"{CONNECTION_TEST_ID}.pdf",
        "content": base64.b64encode(TEST_LETTER_PDF.read_bytes()).decode(),
        "reference": request.json()["reference"],
        "organisationId": ORGANISATION_ID,
        "notificationId": CONNECTION_TEST_ID,
        "callbackUrl": CALLBACK_URL,
    }
    assert len(request.json()["reference"]) == 16
    assert request.headers["X-Api-Key"] == "secret-key"
    assert request.headers["Idempotency-Key"] == CONNECTION_TEST_ID
    assert request.timeout == (5, 15)


def test_a_connection_test_creates_no_notification(notify_db_session, rmock):
    rmock.post(ENDPOINT_URL, json={"id": "job-123"})

    assert _run()["outcome"] == "authorized"

    assert Notification.query.count() == 0
    assert NotificationHistory.query.count() == 0
    assert LetterProviderPin.query.count() == 0
    assert LetterProviderReference.query.count() == 0


def test_a_connection_test_does_not_count_towards_the_provider_metrics(rmock, mocker):
    record = mocker.patch("app.otel_metrics.provider._request_duration.record")
    rmock.post(ENDPOINT_URL, json={})

    _run()

    assert not record.called


@pytest.mark.parametrize(
    "status_code, expected_outcome",
    [
        (200, "authorized"),
        (201, "authorized"),
        (202, "authorized"),
        (302, "connected"),
        (400, "connected"),
        (404, "connected"),
        (415, "connected"),
        (422, "connected"),
        (429, "connected"),
        (500, "connected"),
        (503, "connected"),
        (401, "unauthorized"),
        (403, "unauthorized"),
    ],
)
def test_the_outcome_follows_from_the_endpoints_reply(rmock, status_code, expected_outcome):
    rmock.post(ENDPOINT_URL, text="the reply", status_code=status_code, reason="The Reason")

    result = _run()

    assert result == {
        "state": "finished",
        "outcome": expected_outcome,
        "step": "letter",
        "host": "print.example.com",
        "duration_ms": result["duration_ms"],
        "status_code": status_code,
        "reason": "The Reason",
        "content_type": None,
        "location": None,
        "error": None,
        "timed_out": False,
        "body": "the reply",
        "body_kind": "text",
        "body_truncated": False,
    }


def test_the_reply_is_kept_as_it_was_sent(rmock):
    body = '{\n  "error" :   "adres ontbreekt"\n}\n'
    rmock.post(ENDPOINT_URL, text=body, status_code=422, headers={"Content-Type": "application/problem+json"})

    result = _run()

    assert result["body"] == body
    assert result["content_type"] == "application/problem+json"


def test_a_redirect_shows_where_it_points_to(rmock):
    rmock.post(ENDPOINT_URL, status_code=302, headers={"Location": "https://login.example.com/"})

    result = _run()

    assert result["outcome"] == "connected"
    assert result["location"] == "https://login.example.com/"
    assert result["body_kind"] == "empty"
    assert rmock.call_count == 1


def test_the_host_includes_a_port(rmock):
    rmock.post("https://print.example.com:8443/letters", text="ok")

    assert _run(endpoint_url="https://print.example.com:8443/letters")["host"] == "print.example.com:8443"


def test_oauth_gets_a_token_and_never_keeps_it(rmock):
    rmock.post(TOKEN_URL, json={"access_token": "the-token", "expires_in": 3600})
    rmock.post(ENDPOINT_URL, json={"id": "job-123"}, status_code=201)

    result = _run("oauth", OAUTH)

    assert result["outcome"] == "authorized"
    assert result["step"] == "letter"
    assert result["host"] == "print.example.com"
    assert rmock.last_request.headers["Authorization"] == "Bearer the-token"
    assert "the-token" not in json.dumps(result)


@pytest.mark.parametrize("status_code", [400, 401, 403, 500])
def test_any_refused_token_request_is_unauthorized_and_sends_no_letter(rmock, status_code):
    rmock.post(TOKEN_URL, json={"error": "invalid_client"}, status_code=status_code)
    endpoint = rmock.post(ENDPOINT_URL, json={})

    result = _run("oauth", OAUTH)

    assert result["outcome"] == "unauthorized"
    assert result["step"] == "token"
    assert result["host"] == "idp.example.com"
    assert result["status_code"] == status_code
    assert json.loads(result["body"]) == {"error": "invalid_client"}
    assert not endpoint.called


@pytest.mark.parametrize(
    "reply",
    [
        {"json": {}},
        {"json": ["access_token"]},
        {"text": "<html>login</html>"},
        {"json": {"access_token": "the-token", "expires_in": "soon"}},
    ],
)
def test_a_token_reply_without_a_usable_token_is_unauthorized_and_not_shown(rmock, reply):
    rmock.post(TOKEN_URL, status_code=200, **reply)
    endpoint = rmock.post(ENDPOINT_URL, json={})

    result = _run("oauth", OAUTH)

    assert result["outcome"] == "unauthorized"
    assert result["step"] == "token"
    assert result["status_code"] == 200
    assert result["body"] is None
    assert result["body_kind"] == "unusable_token"
    assert "the-token" not in json.dumps(result)
    assert not endpoint.called


def test_the_endpoint_refusing_the_oauth_token_is_unauthorized(rmock):
    rmock.post(TOKEN_URL, json={"access_token": "the-token", "expires_in": 3600})
    rmock.post(ENDPOINT_URL, json={"error": "invalid_token"}, status_code=401)

    result = _run("oauth", OAUTH)

    assert result["outcome"] == "unauthorized"
    assert result["step"] == "letter"
    assert result["host"] == "print.example.com"


NETWORK_ERROR_TEXTS = {
    "connection-refused": "Connection refused",
    "dns": "Failed to resolve 'print.example.com'",
    "connect-timeout": "timed out",
    "read-timeout": "Read timed out.",
    "connection-closed": "Connection aborted.",
    "chunked-encoding": "Connection broken",
}


@pytest.mark.parametrize(
    "error, expected_outcome, expected_text",
    [(error, "no_connection", NETWORK_ERROR_TEXTS[name]) for name, error in FAILED_TO_CONNECT.items()]
    # the endpoint may have got the letter, so it isn't shown as a connection that failed
    + [(error, "no_reply", NETWORK_ERROR_TEXTS[name]) for name, error in FAILED_AFTER_SENDING.items()],
    ids=NETWORK_ERROR_TEXTS,
)
def test_no_http_reply_shows_the_network_error(rmock, error, expected_outcome, expected_text):
    rmock.post(ENDPOINT_URL, exc=error)

    result = _run()

    assert result["outcome"] == expected_outcome
    assert result["host"] == "print.example.com"
    assert result["status_code"] is None
    assert expected_text in result["error"]
    assert "MaxRetryError" not in result["error"]
    assert result["timed_out"] is False


@pytest.mark.parametrize(
    "error, expected_outcome",
    [(FAILED_TO_CONNECT["dns"], "no_connection"), (FAILED_AFTER_SENDING["read-timeout"], "no_reply")],
)
def test_no_http_reply_from_the_token_url_names_that_host(rmock, error, expected_outcome):
    rmock.post(TOKEN_URL, exc=error)

    result = _run("oauth", OAUTH)

    assert result["outcome"] == expected_outcome
    assert result["step"] == "token"
    assert result["host"] == "idp.example.com"
    assert [request.url for request in rmock.request_history] == [TOKEN_URL]


@pytest.mark.parametrize(
    "auth_method, auth_config, echoed",
    [
        ("api_key", API_KEY, "secret-key"),
        ("api_key", API_KEY, base64.b64encode(b"secret-key").decode()),
        ("basic", {"username": "denhaag", "password": "p@ss w/rd"}, "p@ss w/rd"),
        ("basic", {"username": "denhaag", "password": "p@ss w/rd"}, "p%40ss%20w%2Frd"),
        ("basic", {"username": "denhaag", "password": "p@ss w/rd"}, "p%40ss+w%2Frd"),
        ("basic", {"username": "denhaag", "password": "p@ss w/rd"}, base64.b64encode(b"denhaag:p@ss w/rd").decode()),
        ("basic", {"username": "denhaag", "password": 'p"w<rd'}, 'p\\"w<rd'),
        ("basic", {"username": "denhaag", "password": 'p"w<rd'}, "p&quot;w&lt;rd"),
    ],
)
def test_secrets_the_endpoint_repeats_are_removed(rmock, auth_method, auth_config, echoed):
    rmock.post(ENDPOINT_URL, text=f"before {echoed} after", status_code=401)

    result = _run(auth_method, auth_config)

    assert result["body"] == f"before {REDACTED} after"


def test_the_access_token_is_removed_from_the_endpoints_reply(rmock):
    rmock.post(TOKEN_URL, json={"access_token": "the-token", "expires_in": 3600})
    rmock.post(ENDPOINT_URL, text="token the-token is expired", status_code=401)

    assert _run("oauth", OAUTH)["body"] == f"token {REDACTED} is expired"


def test_the_client_secret_is_removed_from_the_token_urls_reply(rmock):
    rmock.post(TOKEN_URL, text="unknown secret client-secret", status_code=401)

    assert _run("oauth", OAUTH)["body"] == f"unknown secret {REDACTED}"


def test_secrets_are_removed_from_a_redirect_and_a_network_error(rmock):
    rmock.post(ENDPOINT_URL, status_code=302, headers={"Location": "https://login.example.com/?key=secret-key"})
    assert _run()["location"] == f"https://login.example.com/?key={REDACTED}"

    rmock.post(ENDPOINT_URL, exc=requests.ConnectionError("failed with secret-key"))
    assert _run()["error"] == f"failed with {REDACTED}"


def test_a_long_reply_is_cut(rmock):
    rmock.post(ENDPOINT_URL, text="x" * (MAX_BODY_READ * 3), status_code=500)

    result = _run()

    assert result["body"] == "x" * MAX_BODY_SHOWN
    assert result["body_truncated"] is True


def test_a_reply_only_just_over_what_is_shown_is_cut_too(rmock):
    rmock.post(ENDPOINT_URL, text="x" * (MAX_BODY_SHOWN + 1))

    result = _run()

    assert len(result["body"]) == MAX_BODY_SHOWN
    assert result["body_truncated"] is True


def test_a_reply_that_breaks_off_keeps_its_status_and_what_arrived(rmock):
    class BreaksOff:
        def __init__(self):
            self.reads = 0
            self.closed = False

        def read(self, amount=None):
            self.reads += 1
            if self.reads == 1:
                return b"partial"
            raise ProtocolError("Connection broken")

        def close(self):
            self.closed = True

    rmock.post(ENDPOINT_URL, body=BreaksOff(), status_code=500)

    result = _run()

    assert result["outcome"] == "connected"
    assert result["status_code"] == 500
    assert result["body_truncated"] is True


class DripsUntilTheTimeLimit:
    """A reply body whose first chunk arrives, after which the worker's soft time limit goes off while reading."""

    FIRST_CHUNK = b"x" * 8192

    def __init__(self):
        self.reads = 0
        self.closed = False

    def read(self, amount=None):
        self.reads += 1
        if self.reads == 1:
            return self.FIRST_CHUNK
        raise SoftTimeLimitExceeded

    def close(self):
        self.closed = True


def test_the_time_limit_while_reading_the_reply_keeps_its_status_and_what_arrived(notify_api, rmock, mocker):
    log_exception = mocker.patch.object(notify_api.logger, "exception")
    rmock.post(ENDPOINT_URL, body=DripsUntilTheTimeLimit(), status_code=202, reason="Accepted")

    result = _run()

    assert result | {"duration_ms": None} == {
        "state": "finished",
        "outcome": "authorized",
        "step": "letter",
        "host": "print.example.com",
        "duration_ms": None,
        "status_code": 202,
        "reason": "Accepted",
        "content_type": None,
        "location": None,
        "error": None,
        "timed_out": True,
        "body": DripsUntilTheTimeLimit.FIRST_CHUNK.decode(),
        "body_kind": "text",
        "body_truncated": True,
    }
    assert not log_exception.called


def test_the_time_limit_before_any_reply_is_no_reply(notify_api, rmock, mocker):
    log_exception = mocker.patch.object(notify_api.logger, "exception")
    rmock.post(ENDPOINT_URL, exc=SoftTimeLimitExceeded())

    result = _run()

    assert result["outcome"] == "no_reply"
    assert result["host"] == "print.example.com"
    assert result["status_code"] is None
    assert result["timed_out"] is True
    assert result["duration_ms"] is not None
    assert not log_exception.called


def test_the_time_limit_before_any_request_is_a_failed_test_that_says_so(rmock, public_dns):
    # e.g. a DNS lookup that hangs while NotifyNL checks the URL
    public_dns.side_effect = SoftTimeLimitExceeded()

    assert _run() == {
        "state": "finished",
        "outcome": "failed",
        "error": "The test took longer than a connection test may take and was stopped",
    }
    assert not rmock.called


def test_a_binary_reply_is_not_shown(rmock):
    rmock.post(ENDPOINT_URL, content=b"%PDF\x00\x01", headers={"Content-Type": "application/pdf"})

    result = _run()

    assert result["body"] is None
    assert result["body_kind"] == "binary"
    assert result["content_type"] == "application/pdf"


@pytest.mark.parametrize(
    "content, content_type",
    [
        ("café".encode(), "text/plain"),
        ("café".encode(), "application/json"),
        ("café".encode("latin-1"), "text/plain; charset=ISO-8859-1"),
    ],
)
def test_the_reply_is_decoded(rmock, content, content_type):
    rmock.post(ENDPOINT_URL, content=content, headers={"Content-Type": content_type})

    assert _run()["body"] == "café"


def test_notifynl_refusing_the_url_when_sending_calls_nothing(rmock):
    result = _run(endpoint_url="http://print.example.com/letters")

    assert result == {
        "state": "finished",
        "outcome": "failed",
        "error": "http://print.example.com/letters must use https",
    }
    assert not rmock.called


def test_an_unexpected_failure_is_a_failed_test_without_details(rmock, mocker):
    mocker.patch(
        "app.letters_nl.letter_endpoint_connection.ConnectionTestLetterClient.send_test_letter",
        side_effect=RuntimeError("something internal"),
    )

    assert _run() == {"state": "finished", "outcome": "failed"}


def test_a_test_whose_result_has_expired_sends_nothing(rmock, redis_results):
    # e.g. it waited in the queue behind real letters for longer than admin waits
    redis_results.clear()

    assert _run() is None
    assert not rmock.called


def test_a_redis_error_while_checking_for_the_result_is_a_failed_test_not_a_skipped_one(rmock, redis_results, mocker):
    def get(key, raise_exception=False, **kwargs):
        # RedisClient only raises when asked to, and returns None otherwise
        if raise_exception:
            raise RedisConnectionError("Redis is gone")
        return redis_results.get(key)

    mocker.patch("app.letters_nl.letter_endpoint_connection.redis_store.get", side_effect=get)

    assert _run() == {"state": "finished", "outcome": "failed"}
    assert not rmock.called


def test_the_result_says_which_host_is_being_waited_on(rmock):
    seen_while_sending = {}

    def reply(request, context):
        seen_while_sending.update(get_connection_test_result(ORGANISATION_ID, CONNECTION_TEST_ID))
        return "ok"

    rmock.post(ENDPOINT_URL, text=reply)

    _run()

    assert seen_while_sending == {"state": "running", "host": "print.example.com"}


def test_a_new_test_starts_queued_and_can_only_be_read_by_its_organisation():
    test_id = create_connection_test(ORGANISATION_ID)

    assert get_connection_test_result(ORGANISATION_ID, test_id) == {"state": "queued"}
    assert get_connection_test_result("another-organisation", test_id) is None
