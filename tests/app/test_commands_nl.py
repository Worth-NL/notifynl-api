import json
from unittest.mock import mock_open

import pytest

from app import db
from app.clients.letter.pingen import PingenClient
from app.commands import register_pingen_webhook, sync_org_boundaries_geojson
from tests.app.db import create_organisation
from tests.conftest import set_config_values


def test_sync_org_boundaries_geojson(notify_db_session, notify_api, mocker):
    org_with_boundary = create_organisation(name="Gemeente Den Haag")
    org_with_boundary.area_boundary = {
        "type": "Polygon",
        "coordinates": [[[4.30, 52.07], [4.32, 52.07], [4.32, 52.09], [4.30, 52.09], [4.30, 52.07]]],
    }
    db.session.commit()

    create_organisation(name="Gemeente Zonder Grens")

    mocker.patch("app.commands.open", mock_open(read_data="fake-token"))
    mocker.patch.dict(
        "os.environ",
        {"KUBERNETES_SERVICE_HOST": "kubernetes.default.svc", "KUBERNETES_SERVICE_PORT": "443"},
    )
    mock_patch = mocker.patch("app.commands.requests.patch")
    mock_patch.return_value.raise_for_status.return_value = None

    notify_api.test_cli_runner().invoke(sync_org_boundaries_geojson)

    assert mock_patch.call_count == 1
    args, kwargs = mock_patch.call_args
    assert args[0] == (
        "https://kubernetes.default.svc:443/api/v1/namespaces/fake-token/configmaps/notifynl-org-boundaries"
    )
    assert kwargs["headers"]["Authorization"] == "Bearer fake-token"

    body = json.loads(kwargs["data"])
    feature_collection = json.loads(body["data"]["notifynl-org-boundaries.json"])

    assert feature_collection["type"] == "FeatureCollection"
    assert len(feature_collection["features"]) == 1
    assert feature_collection["features"][0]["properties"]["organisation_name"] == "Gemeente Den Haag"
    assert feature_collection["features"][0]["geometry"] == org_with_boundary.area_boundary


PINGEN_API = "https://api-staging.pingen.com"
PINGEN_WEBHOOKS_URL = f"{PINGEN_API}/organisations/pingen-org/webhooks"
SIGNING_KEY = "0123456789abcdef0123"
WEBHOOK_URL = "https://api.notifynl.nl/notifications/letter/pingen"


@pytest.fixture
def pingen(notify_api, mocker, rmock):
    with set_config_values(
        notify_api,
        {
            "API_HOST_NAME": "https://api.notifynl.nl",
            "PINGEN_API_URL": PINGEN_API,
            "PINGEN_IDENTITY_URL": "https://identity-staging.pingen.com",
            "PINGEN_CLIENT_ID": "client-id",
            "PINGEN_CLIENT_SECRET": "client-secret",
            "PINGEN_ORGANISATION_ID": "pingen-org",
            "PINGEN_WEBHOOK_SIGNING_KEY": SIGNING_KEY,
        },
    ):
        mocker.patch("app.commands.get_pingen_client", return_value=PingenClient(notify_api, mocker.Mock()))
        rmock.post(
            "https://identity-staging.pingen.com/auth/access-tokens", json={"expires_in": 43200, "access_token": "t"}
        )
        rmock.post(PINGEN_WEBHOOKS_URL, status_code=201, json={"data": {"id": "new", "type": "webhooks"}})
        yield rmock


def _registered(rmock, *webhooks):
    rmock.get(
        PINGEN_WEBHOOKS_URL,
        json={
            "data": [
                {
                    "id": webhook_id,
                    "type": "webhooks",
                    "attributes": {"event_category": category, "url": url, "signing_key": signing_key},
                }
                for webhook_id, category, url, signing_key in webhooks
            ]
        },
    )


def _created(rmock):
    return [
        request.json()["data"]["attributes"]
        for request in rmock.request_history
        if request.method == "POST" and request.url == PINGEN_WEBHOOKS_URL
    ]


def test_register_pingen_webhook_registers_every_letter_event_category(notify_api, pingen):
    _registered(pingen)

    result = notify_api.test_cli_runner().invoke(register_pingen_webhook)

    assert result.exit_code == 0, result.output
    assert _created(pingen) == [
        {"event_category": category, "url": WEBHOOK_URL, "signing_key": SIGNING_KEY}
        for category in ("sent", "delivered", "undeliverable", "issues")
    ]


def test_register_pingen_webhook_leaves_registered_webhooks_alone(notify_api, pingen):
    _registered(
        pingen,
        ("w1", "sent", "https://tunnel.example.com/notifications/letter/pingen", SIGNING_KEY),
        ("w2", "issues", "https://tunnel.example.com/notifications/letter/pingen", SIGNING_KEY),
        # another environment's webhook
        ("w3", "delivered", WEBHOOK_URL.replace("api.", "api.acc."), SIGNING_KEY),
    )

    result = notify_api.test_cli_runner().invoke(
        register_pingen_webhook, ["--url", "https://tunnel.example.com/notifications/letter/pingen"]
    )

    assert result.exit_code == 0, result.output
    assert [webhook["event_category"] for webhook in _created(pingen)] == ["delivered", "undeliverable"]


def test_register_pingen_webhook_reports_webhooks_signed_with_another_key(notify_api, pingen):
    _registered(pingen, ("w1", "sent", WEBHOOK_URL, "another-signing-key-0123"))

    result = notify_api.test_cli_runner().invoke(register_pingen_webhook)

    assert result.exit_code == 1
    assert "signed with another key" in result.output
    assert "sent (w1)" in result.output
    assert [webhook["event_category"] for webhook in _created(pingen)] == ["delivered", "undeliverable", "issues"]


@pytest.mark.parametrize("signing_key", [None, "too-short", "x" * 33])
def test_register_pingen_webhook_needs_a_signing_key_pingen_accepts(notify_api, pingen, signing_key):
    with set_config_values(notify_api, {"PINGEN_WEBHOOK_SIGNING_KEY": signing_key}):
        result = notify_api.test_cli_runner().invoke(register_pingen_webhook)

    assert result.exit_code == 1
    assert "20 to 32 characters" in result.output
    assert not pingen.request_history


def test_register_pingen_webhook_reports_pingen_errors(notify_api, pingen):
    pingen.get(PINGEN_WEBHOOKS_URL, status_code=403, json={"errors": [{"title": "Forbidden", "detail": "scope"}]})

    result = notify_api.test_cli_runner().invoke(register_pingen_webhook)

    assert result.exit_code == 1
    assert "403" in result.output
