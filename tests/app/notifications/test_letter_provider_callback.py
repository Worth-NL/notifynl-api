import hmac
import json
import uuid
from hashlib import sha256

import pytest
from flask import url_for

from app import signing
from app.celery.letter_provider_tasks import process_letter_provider_status
from tests.app.db_nl import create_letter_provider_reference
from tests.conftest import set_config

SIGNING_KEY = "0123456789abcdef0123456789abcdef"
PINGEN_LETTER_ID = "5c6a1a53-5f8a-4bd1-9d2b-2f3a4b5c6d7e"


@pytest.fixture
def mock_status_task(mock_celery_task):
    return mock_celery_task(process_letter_provider_status)


@pytest.fixture
def pingen_signing_key(notify_api):
    with set_config(notify_api, "PINGEN_WEBHOOK_SIGNING_KEY", SIGNING_KEY):
        yield


def _post_status(client, token, data):
    return client.post(
        url_for("letter_provider_callback.process_letter_provider_callback", token=token),
        data=json.dumps(data),
    )


@pytest.mark.parametrize("status", ["delivered", "permanent-failure", "technical-failure", "returned-letter"])
def test_letter_provider_callback_queues_the_status_update(client, mock_status_task, status):
    notification_id = str(uuid.uuid4())

    response = _post_status(client, signing.encode(notification_id), {"status": status, "reason": "because"})

    assert response.status_code == 204
    mock_status_task.assert_called_once_with(
        kwargs={"notification_id": notification_id, "provider": "rest-endpoint", "status": status, "reason": "because"},
        queue="letter-callbacks",
    )


@pytest.mark.parametrize("token", ["", "not-signed", "tampered"])
def test_letter_provider_callback_requires_a_signed_token(client, mock_status_task, token):
    if token == "tampered":
        token = signing.encode(str(uuid.uuid4()))[:-2] + "xx"

    response = _post_status(client, token, {"status": "delivered"})

    assert response.status_code == 403
    assert not mock_status_task.called


@pytest.mark.parametrize(
    "data", [{}, {"status": "sent"}, {"status": "sending"}, {"status": "delivered", "occurred_at": "yesterday"}]
)
def test_letter_provider_callback_validates_the_status(client, mock_status_task, data):
    response = _post_status(client, signing.encode(str(uuid.uuid4())), data)

    assert response.status_code == 400
    assert not mock_status_task.called


def _pingen_webhook(webhook_type, letter_id=PINGEN_LETTER_ID, deliverable_type="letters", reason=None):
    attributes = {
        "url": "https://api.notifynl.nl/notifications/letter/pingen",
        "created_at": "2026-09-29T12:00:00+0200",
    }
    if reason:
        attributes["reason"] = reason
    return json.dumps(
        {
            "data": {
                "id": "9a8b7c6d-0000-4000-8000-000000000001",
                "type": webhook_type,
                "attributes": attributes,
                "relationships": {
                    "organisation": {"data": {"id": "9a8b7c6d-0000-4000-8000-000000000002", "type": "organisations"}},
                    "deliverable": {"data": {"id": letter_id, "type": deliverable_type}},
                    "event": {"data": {"id": "9a8b7c6d-0000-4000-8000-000000000003", "type": "deliverables_events"}},
                },
            }
        }
    ).encode()


def _post_pingen(client, payload, signature=None):
    return client.post(
        url_for("letter_provider_callback.process_pingen_webhook"),
        data=payload,
        headers={"Signature": signature or hmac.new(SIGNING_KEY.encode(), payload, sha256).hexdigest()},
    )


@pytest.mark.parametrize(
    "webhook_type, status, reason",
    [
        ("webhook_sent", "delivered", None),
        ("webhook_delivered", "delivered", None),
        ("webhook_undeliverable", "returned-letter", "Recipient could not be determined at the specified address."),
        ("webhook_issues", "technical-failure", "Content failed inspection"),
    ],
)
def test_pingen_webhook_queues_the_status_update(
    client, notify_db_session, pingen_signing_key, mock_status_task, webhook_type, status, reason
):
    notification_id = uuid.uuid4()
    create_letter_provider_reference(notification_id, "pingen", PINGEN_LETTER_ID)

    response = _post_pingen(client, _pingen_webhook(webhook_type, reason=reason))

    assert response.status_code == 200
    mock_status_task.assert_called_once_with(
        kwargs={"notification_id": str(notification_id), "provider": "pingen", "status": status, "reason": reason},
        queue="letter-callbacks",
    )


@pytest.mark.parametrize(
    "payload",
    [
        # e.g. a letter sent through notifynl-dvla-service
        _pingen_webhook("webhook_sent", letter_id="00000000-0000-0000-0000-000000000000"),
        _pingen_webhook("webhook_sent", deliverable_type="emails"),
        _pingen_webhook("webhook_channel_subscriptions"),
    ],
    ids=["unknown-letter", "not-a-letter", "unknown-webhook-type"],
)
def test_pingen_webhook_acknowledges_what_it_cannot_act_on(
    client, notify_db_session, pingen_signing_key, mock_status_task, payload
):
    create_letter_provider_reference(uuid.uuid4(), "pingen", PINGEN_LETTER_ID)

    response = _post_pingen(client, payload)

    assert response.status_code == 200
    assert response.json == {"result": "ignored"}
    assert not mock_status_task.called


def test_pingen_webhook_rejects_an_invalid_signature(client, notify_db_session, pingen_signing_key, mock_status_task):
    payload = _pingen_webhook("webhook_sent")

    response = _post_pingen(client, payload, signature=hmac.new(b"wrong key", payload, sha256).hexdigest())

    assert response.status_code == 401
    assert not mock_status_task.called


def test_pingen_webhook_rejects_a_tampered_payload(client, notify_db_session, pingen_signing_key, mock_status_task):
    signature = hmac.new(SIGNING_KEY.encode(), _pingen_webhook("webhook_sent"), sha256).hexdigest()

    response = _post_pingen(client, _pingen_webhook("webhook_issues"), signature=signature)

    assert response.status_code == 401


def test_pingen_webhook_without_a_configured_signing_key(client, notify_api, mock_status_task):
    with set_config(notify_api, "PINGEN_WEBHOOK_SIGNING_KEY", None):
        response = _post_pingen(client, _pingen_webhook("webhook_sent"), signature="anything")

    assert response.status_code == 401


def test_pingen_webhook_with_an_invalid_payload(client, pingen_signing_key, mock_status_task):
    response = _post_pingen(client, b'{"data": {"type": "webhook_sent"}}')

    assert response.status_code == 400
