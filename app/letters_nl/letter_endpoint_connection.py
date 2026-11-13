"""
The "Verbinding testen" button on the print endpoint settings: sends a fixed PDF to the endpoint an organisation is
setting up, with the values typed in the form, and keeps the endpoint's reply for admin to show. Nothing is saved and
no notification exists for it: the letter only lives in memory and the result expires from Redis.

Only platform admins can start a test: it presents NotifyNL's client certificate to the host that was typed in.
"""

import base64
import html
import json
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from time import monotonic, time
from urllib.parse import quote, quote_plus, urlsplit
from uuid import uuid4

import requests
from celery.exceptions import SoftTimeLimitExceeded
from flask import current_app
from redis.exceptions import LockError, RedisError
from urllib3.exceptions import MaxRetryError, NameResolutionError

from app import create_random_identifier, encryption, redis_store
from app.clients.letter import (
    Letter,
    LetterClientException,
    LetterClientRetryableException,
    may_have_reached_the_provider,
)
from app.clients.letter.rest_endpoint import RestEndpointLetterClient
from app.letters_nl.constants import AUTH_METHOD_BASIC, SECRET_AUTH_CONFIG_FIELDS

# (connect, read): shorter than for real letters, as someone is waiting for this and the file is one page
CONNECTION_TEST_TIMEOUT = (5, 15)
CONNECTION_TEST_RESULT_TTL_SECONDS = 15 * 60
CONNECTION_TEST_RATE_LIMIT = 20
CONNECTION_TEST_RATE_INTERVAL_SECONDS = 60 * 60
# the letter worker's time limits for a test: an endpoint can drip its reply for as long as each read stays within the
# read timeout, and these workers send real letters
CONNECTION_TEST_SOFT_TIME_LIMIT = 60
CONNECTION_TEST_TIME_LIMIT = 70
# a test still running this long after it started was killed by the hard time limit, so nothing will finish it
CONNECTION_TEST_OVERDUE_SECONDS = CONNECTION_TEST_TIME_LIMIT + 10
# tests take the letter worker's slots from real letters: one at a time per organisation, and only a few overall
CONNECTION_TEST_GLOBAL_LIMIT = 2
# held from the start until the test is done, and a test can wait in the queue for as long as its result is kept
CONNECTION_TEST_LOCK_TTL_SECONDS = CONNECTION_TEST_RESULT_TTL_SECONDS + CONNECTION_TEST_OVERDUE_SECONDS
# an endpoint decides how much it sends back
MAX_BODY_READ = 64 * 1024
MAX_BODY_SHOWN = 10 * 1024
REDACTED = "[verborgen]"
TEST_LETTER_PDF = Path(__file__).with_name("connection_test.pdf")

STATE_QUEUED = "queued"
STATE_RUNNING = "running"
STATE_FINISHED = "finished"

OUTCOME_AUTHORIZED = "authorized"
OUTCOME_CONNECTED = "connected"
OUTCOME_UNAUTHORIZED = "unauthorized"
OUTCOME_NO_CONNECTION = "no_connection"
# the request went out (or may have), but no reply came back
OUTCOME_NO_REPLY = "no_reply"
OUTCOME_FAILED = "failed"

STEP_TOKEN = "token"
STEP_LETTER = "letter"

BODY_TEXT = "text"
BODY_EMPTY = "empty"
BODY_BINARY = "binary"
BODY_UNUSABLE_TOKEN = "unusable_token"

# what kind of network error a test ran into: its text can name internal hosts and certificates
ERROR_DNS = "dns"
ERROR_CONNECT = "connect"
ERROR_CONNECT_TIMEOUT = "connect_timeout"
ERROR_TLS = "tls"
ERROR_READ_TIMEOUT = "read_timeout"
ERROR_CLOSED = "closed"
ERROR_OTHER = "other"

STOPPED = "The test took longer than a connection test may take and was stopped"


class ConnectionTestRefused(Exception):
    """A connection test that can't start now. `status_code` is what the API answers."""

    status_code = 400


class ConnectionTestBusy(ConnectionTestRefused):
    status_code = 409


class ConnectionTestLimitReached(ConnectionTestRefused):
    status_code = 429


class ConnectionTestUnavailable(ConnectionTestRefused):
    status_code = 503


@dataclass(frozen=True)
class ConnectionTestSettings:
    """The part of an OrganisationLetterProvider that RestEndpointLetterClient reads, from typed values."""

    endpoint_url: str
    auth_method: str
    auth_config: dict


@dataclass
class Exchange:
    url: str
    sends_the_letter: bool
    status_code: int | None = None
    reason: str = ""
    content_type: str | None = None
    location: str | None = None
    encoding: str | None = None
    body: bytes = b""
    body_truncated: bool = False
    # one of the ERROR_ kinds when no HTTP reply came back
    error_kind: str | None = None
    # whether the endpoint may have received the request although no reply came back, e.g. after a read timeout
    may_have_arrived: bool = False
    # the worker's time limit stopped this exchange
    timed_out: bool = False
    duration_ms: int | None = None

    @property
    def is_success(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300

    def stop_waiting(self):
        """Called when the worker's time limit cuts the exchange off: what arrived until then is kept."""
        self.timed_out = True
        if self.status_code is not None:
            self.body_truncated = True


class ConnectionTestLetterClient(RestEndpointLetterClient):
    """Sends letters like its parent, and remembers what the last request got back. Used once per test."""

    timeout = CONNECTION_TEST_TIMEOUT

    def __init__(self, current_app, on_request: Callable[[str], None]):
        super().__init__(current_app)
        self.on_request = on_request
        self.exchange: Exchange | None = None
        self.access_tokens: list[str] = []

    def send_test_letter(self, letter: Letter, settings: ConnectionTestSettings):
        # not try_send_letter: tests shouldn't count towards the provider's request duration metrics
        self._send_letter(letter, settings)

    def _get_oauth_token(self, auth_config: dict) -> str:
        token = super()._get_oauth_token(auth_config)
        self.access_tokens.append(token)
        return token

    def _request(self, method: str, url: str, sends_the_letter: bool = False, **kwargs) -> requests.Response:
        self.on_request(_host(url))
        exchange = self.exchange = Exchange(url=url, sends_the_letter=sends_the_letter)
        started = monotonic()
        try:
            response = super()._request(method, url, sends_the_letter=sends_the_letter, stream=True, **kwargs)
            return _read_reply(response, exchange)
        except LetterClientRetryableException as e:
            exchange.error_kind = _error_kind(e.__cause__)
            exchange.may_have_arrived = may_have_reached_the_provider(e.__cause__)
            raise
        finally:
            exchange.duration_ms = round((monotonic() - started) * 1000)


def _read_reply(response: requests.Response, exchange: Exchange) -> requests.Response:
    """Records the reply, and returns a response holding just the part of its body that was read."""
    exchange.status_code = response.status_code
    exchange.reason = str(response.reason or "")
    exchange.content_type = response.headers.get("Content-Type")
    exchange.location = response.headers.get("Location")
    exchange.encoding = response.encoding

    body = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=8192):
            body += chunk
            if len(body) > MAX_BODY_READ:
                exchange.body_truncated = True
                break
    except requests.RequestException:
        # the endpoint did answer: the status counts, and the body is shown as far as it got
        exchange.body_truncated = True
    finally:
        # also when the worker's time limit stops the read
        exchange.body = bytes(body[:MAX_BODY_READ])
        response.close()

    bounded = requests.Response()
    bounded.status_code = response.status_code
    bounded.reason = response.reason
    bounded.headers = response.headers
    bounded.url = response.url
    bounded.encoding = response.encoding
    bounded.raw = BytesIO(exchange.body)
    return bounded


def _error_kind(error: BaseException | None) -> str:
    """
    Only the kind of network error, not its text: that can name internal hosts and certificates, as the host is
    resolved again after the URL check (DNS can change in between).
    """
    # SSLError and ConnectTimeout are ConnectionErrors too
    if isinstance(error, requests.exceptions.SSLError):
        return ERROR_TLS
    if isinstance(error, requests.ConnectTimeout):
        return ERROR_CONNECT_TIMEOUT
    if isinstance(error, requests.ReadTimeout):
        return ERROR_READ_TIMEOUT
    if isinstance(error, requests.ConnectionError):
        cause = error.args[0] if error.args else None
        if isinstance(cause, MaxRetryError):
            return ERROR_DNS if isinstance(cause.reason, NameResolutionError) else ERROR_CONNECT
        # urllib3 only raises errors after the request went out as they are, such as the connection being closed
        return ERROR_CLOSED
    if isinstance(error, requests.exceptions.ChunkedEncodingError):
        return ERROR_CLOSED
    return ERROR_OTHER


def _host(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.hostname}:{parts.port}" if parts.port else str(parts.hostname)


def start_connection_test(organisation_id) -> str:
    """
    Stores a new test as queued and returns its id, holding a run for it until release_connection_test. Raises a
    ConnectionTestRefused when it can't start: rather than without the Redis it needs, or next to the tests already
    taking the letter worker's slots.
    """
    if not redis_store.active:
        # without Redis nothing would limit the tests, and the worker's result couldn't reach admin
        raise ConnectionTestUnavailable("Connection tests need Redis")

    test_id = str(uuid4())
    try:
        if not _hold_a_run(organisation_id, test_id):
            raise ConnectionTestBusy("A connection test is already running")
        try:
            if _exceeded_rate_limit(organisation_id, test_id):
                raise ConnectionTestLimitReached("Too many connection tests")
            redis_store.set(
                _result_key(organisation_id, test_id),
                json.dumps({"state": STATE_QUEUED}),
                ex=CONNECTION_TEST_RESULT_TTL_SECONDS,
                raise_exception=True,
            )
        except BaseException:
            release_connection_test(organisation_id, test_id)
            raise
    except RedisError as e:
        raise ConnectionTestUnavailable("Connection tests need Redis") from e
    return test_id


def release_connection_test(organisation_id, test_id: str):
    """Lets the next test start. Only frees what this test holds; what it can't free expires by itself."""
    if not redis_store.active:
        return
    for key in (_organisation_run_key(organisation_id), *map(_global_run_key, range(CONNECTION_TEST_GLOBAL_LIMIT))):
        try:
            _run_lock(key).do_release(test_id)
        except LockError:
            pass  # not held by this test
        except RedisError:
            current_app.logger.warning(
                "Could not release %s for letter endpoint connection test %s",
                key,
                test_id,
                exc_info=True,
                extra={"connection_test_id": test_id},
            )


def _hold_a_run(organisation_id, test_id: str) -> bool:
    if not _run_lock(_organisation_run_key(organisation_id)).acquire(token=test_id):
        return False
    if any(_run_lock(_global_run_key(slot)).acquire(token=test_id) for slot in range(CONNECTION_TEST_GLOBAL_LIMIT)):
        return True
    _run_lock(_organisation_run_key(organisation_id)).do_release(test_id)
    return False


def _run_lock(key: str):
    return redis_store.get_lock(key, timeout=CONNECTION_TEST_LOCK_TTL_SECONDS, blocking=False, thread_local=False)


def _organisation_run_key(organisation_id) -> str:
    return f"letter-endpoint-connection-test-running-{organisation_id}"


def _global_run_key(slot: int) -> str:
    return f"letter-endpoint-connection-test-slot-{slot}"


def _exceeded_rate_limit(organisation_id, test_id: str) -> bool:
    """
    Like RedisClient.exceeded_rate_limit, except that a refused test doesn't count (clicking on would extend the
    wait), and a Redis error raises instead of allowing the test. Only called while holding the organisation's run.
    """
    key = f"letter-endpoint-connection-test-limit-{organisation_id}"
    now = time()
    pipe = redis_store.redis_store.pipeline()
    pipe.zremrangebyscore(key, "-inf", now - CONNECTION_TEST_RATE_INTERVAL_SECONDS)
    pipe.zcard(key)
    if pipe.execute()[1] >= CONNECTION_TEST_RATE_LIMIT:
        return True
    pipe = redis_store.redis_store.pipeline()
    pipe.zadd(key, {test_id: now})
    pipe.expire(key, CONNECTION_TEST_RATE_INTERVAL_SECONDS)
    pipe.execute()
    return False


def encrypt_connection_test_settings(endpoint_url: str, auth_method: str, auth_config: dict) -> str:
    # the typed secrets travel to the worker through the queue
    return encryption.encrypt(
        json.dumps({"endpoint_url": endpoint_url, "auth_method": auth_method, "auth_config": auth_config})
    )


def get_connection_test_result(organisation_id, test_id) -> dict | None:
    result = redis_store.get(_result_key(organisation_id, test_id), skippable=False)
    if not result:
        return None
    result = json.loads(result)
    # tests stored before started_at existed have none, and expire anyway
    started_at = result.get("started_at")
    if result["state"] == STATE_RUNNING and started_at and time() - started_at > CONNECTION_TEST_OVERDUE_SECONDS:
        # the worker's hard time limit killed the test, so nothing else will finish it
        result = {"state": STATE_FINISHED, "outcome": OUTCOME_FAILED, "host": result["host"], "error": STOPPED}
        _store_result(organisation_id, test_id, result)
        release_connection_test(organisation_id, test_id)
    return result


def run_connection_test(organisation_id, test_id: str, encrypted_settings: str, callback_url: str):
    try:
        _run_connection_test(organisation_id, test_id, encrypted_settings, callback_url)
    finally:
        # also when it was skipped or failed, so the next test can start straight away
        release_connection_test(organisation_id, test_id)


def _run_connection_test(organisation_id, test_id: str, encrypted_settings: str, callback_url: str):
    started_at = time()
    try:
        if not _is_awaited(organisation_id, test_id):
            # e.g. it waited behind real letters in the queue for longer than its result is kept: admin already
            # shows it as expired, so the letter would be sent for nothing
            current_app.logger.info(
                "Not running letter endpoint connection test %s of organisation %s: its result has expired",
                test_id,
                organisation_id,
                extra={"connection_test_id": test_id, "organisation_id": str(organisation_id)},
            )
            return

        settings = ConnectionTestSettings(**json.loads(encryption.decrypt(encrypted_settings)))
        client = ConnectionTestLetterClient(
            current_app,
            lambda host: _store_result(
                organisation_id, test_id, {"state": STATE_RUNNING, "host": host, "started_at": started_at}
            ),
        )
        letter = Letter(
            notification_id=test_id,
            reference=create_random_identifier(),
            organisation_id=str(organisation_id),
            pdf=TEST_LETTER_PDF.read_bytes(),
            postage="netherlands",
            callback_url=callback_url,
        )
        failure = None
        try:
            client.send_test_letter(letter, settings)
        except SoftTimeLimitExceeded:
            # e.g. an endpoint that drips its reply: what arrived until now is still worth showing
            failure = TimeoutError(STOPPED)
            if client.exchange:
                client.exchange.stop_waiting()
        except (LetterClientException, ValueError, KeyError, TypeError, AttributeError) as e:
            # also an unusable token reply. What happened is read from the last exchange, not from this error
            failure = e
        result = _finished_result(client, settings, failure)
    except Exception:
        current_app.logger.exception(
            "Letter endpoint connection test %s failed unexpectedly", test_id, extra={"connection_test_id": test_id}
        )
        result = {"state": STATE_FINISHED, "outcome": OUTCOME_FAILED}

    _store_result(organisation_id, test_id, result)
    # never the reply itself: it comes from outside and can hold anything
    current_app.logger.info(
        "Letter endpoint connection test %s of organisation %s: %s",
        test_id,
        organisation_id,
        result["outcome"],
        extra={
            "connection_test_id": test_id,
            "organisation_id": str(organisation_id),
            "connection_test_outcome": result["outcome"],
            "connection_test_host": result.get("host"),
            "connection_test_status_code": result.get("status_code"),
        },
    )


def _finished_result(
    client: ConnectionTestLetterClient, settings: ConnectionTestSettings, failure: BaseException | None
) -> dict:
    secrets = _secret_forms(settings, client.access_tokens)
    exchange = client.exchange
    if exchange is None:
        # NotifyNL stopped before calling anything, e.g. the URL now resolves to an internal address
        return {"state": STATE_FINISHED, "outcome": OUTCOME_FAILED, "error": _redact(str(failure), secrets)}

    return {
        "state": STATE_FINISHED,
        "outcome": _outcome(exchange),
        "step": STEP_LETTER if exchange.sends_the_letter else STEP_TOKEN,
        "host": _host(exchange.url),
        "duration_ms": exchange.duration_ms,
        "status_code": exchange.status_code,
        "reason": _redact(exchange.reason, secrets),
        "content_type": exchange.content_type,
        "location": _redact(exchange.location, secrets) if exchange.location else None,
        "error_kind": exchange.error_kind,
        "timed_out": exchange.timed_out,
        **_body_fields(exchange, secrets),
    }


def _outcome(exchange: Exchange) -> str:
    if exchange.status_code is None:
        # a read timeout or a closed connection can come after the endpoint got the request, unlike a refused one
        return OUTCOME_NO_REPLY if exchange.may_have_arrived or exchange.timed_out else OUTCOME_NO_CONNECTION
    if not exchange.sends_the_letter:
        # the token request is only the last one when it gave no usable token, so the letter was never sent
        return OUTCOME_UNAUTHORIZED
    if exchange.status_code in (401, 403):
        return OUTCOME_UNAUTHORIZED
    return OUTCOME_AUTHORIZED if exchange.is_success else OUTCOME_CONNECTED


def _body_fields(exchange: Exchange, secrets: list[str]) -> dict:
    if not exchange.sends_the_letter and exchange.is_success:
        # a token reply we couldn't use can still hold the token
        return {"body": None, "body_kind": BODY_UNUSABLE_TOKEN, "body_truncated": False}
    if not exchange.body:
        return {"body": None, "body_kind": BODY_EMPTY, "body_truncated": exchange.body_truncated}
    if b"\0" in exchange.body:
        return {"body": None, "body_kind": BODY_BINARY, "body_truncated": exchange.body_truncated}

    # secrets first: cutting the text could leave half of one behind
    text = _redact(_decode(exchange.body, exchange.encoding), secrets)
    return {
        "body": text[:MAX_BODY_SHOWN],
        "body_kind": BODY_TEXT,
        "body_truncated": exchange.body_truncated or len(text) > MAX_BODY_SHOWN,
    }


def _decode(body: bytes, encoding: str | None) -> str:
    # UTF-8 first: requests assumes ISO-8859-1 for any text without a charset
    for candidate in ("utf-8", encoding or "utf-8"):
        try:
            return body.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace")


def _secret_forms(settings: ConnectionTestSettings, access_tokens: list[str]) -> list[str]:
    """Every way an endpoint is likely to repeat a secret we sent it, longest first so none is left half replaced."""
    auth_config = settings.auth_config
    secrets = [auth_config.get(field) for field in SECRET_AUTH_CONFIG_FIELDS] + access_tokens
    if settings.auth_method == AUTH_METHOD_BASIC:
        secrets.append(f"{auth_config.get('username')}:{auth_config.get('password')}")

    forms = set()
    for secret in filter(None, secrets):
        forms |= {
            secret,
            quote(secret, safe=""),
            quote_plus(secret),
            base64.b64encode(secret.encode()).decode("ascii"),
            json.dumps(secret)[1:-1],
            html.escape(secret),
        }
    return sorted(forms, key=len, reverse=True)


def _redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    return text


def _is_awaited(organisation_id, test_id: str) -> bool:
    # a Redis error raises instead of reading as expired, which would drop the test without a word
    return redis_store.get(_result_key(organisation_id, test_id), skippable=False, raise_exception=True) is not None


def _store_result(organisation_id, test_id: str, result: dict):
    redis_store.set(_result_key(organisation_id, test_id), json.dumps(result), ex=CONNECTION_TEST_RESULT_TTL_SECONDS)


def _result_key(organisation_id, test_id) -> str:
    return f"letter-endpoint-connection-test-{organisation_id}-{test_id}"
