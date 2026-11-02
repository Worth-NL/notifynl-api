from unittest import mock

import pytest
import requests_mock

from app import signing
from app.celery.service_callback_tasks import (
    _send_data_to_service_callback_api,
    create_delivery_status_callback_data,
)
from tests.app.db import (
    create_notification_history,
    create_service,
    create_service_callback_api,
    create_template,
)
from tests.conftest import set_config, set_config_values


def test_create_delivery_status_callback_data_for_notification_history(notify_db_session):
    # a provider can report back after the notification has moved to notification_history,
    # which has no `to` column
    service = create_service()
    template = create_template(service=service, template_type="letter")
    callback_api = create_service_callback_api(service=service, callback_type="delivery_status")
    notification = create_notification_history(
        template=template, status="delivered", client_reference="my-ref", sent_by="pingen"
    )

    data = signing.decode(create_delivery_status_callback_data(notification, callback_api))

    assert data["notification_id"] == str(notification.id)
    assert data["notification_to"] is None
    assert data["notification_status"] == "delivered"
    assert data["notification_client_reference"] == "my-ref"


@pytest.mark.parametrize("has_certificate", [True, False])
def test_send_data_to_service_callback_api_presents_client_certificate_for_host(notify_api, tmp_path, has_certificate):
    callback_url = "https://wsgateway-extern.denhaag.nl/callback"
    certificate = tmp_path / "wsgateway-extern-denhaag-nl.pem"
    if has_certificate:
        certificate.write_text("cert and key")
    celery_task_mock = mock.MagicMock()
    celery_task_mock.name = "my-task-name"

    with set_config(notify_api, "SSL_CERT_DIR", str(tmp_path)), requests_mock.Mocker() as request_mock:
        request_mock.post(callback_url, json={}, status_code=200)
        _send_data_to_service_callback_api(celery_task_mock, {"id": "hello"}, callback_url, "my-token", "hello", {})

    assert request_mock.request_history[0].cert == (str(certificate) if has_certificate else None)


def test_send_data_to_service_callback_api_presents_default_client_certificate(notify_api, tmp_path):
    callback_url = "https://callbacks.eindhoven.nl/notify"
    default_certificate = tmp_path / "client.pem"
    default_certificate.write_text("cert and key")
    celery_task_mock = mock.MagicMock()
    celery_task_mock.name = "my-task-name"

    with (
        set_config_values(
            notify_api, {"SSL_CERT_DIR": str(tmp_path), "SSL_DEFAULT_CLIENT_CERT": str(default_certificate)}
        ),
        requests_mock.Mocker() as request_mock,
    ):
        request_mock.post(callback_url, json={}, status_code=200)
        _send_data_to_service_callback_api(celery_task_mock, {"id": "hello"}, callback_url, "my-token", "hello", {})

    assert request_mock.request_history[0].cert == str(default_certificate)


@pytest.mark.parametrize("ca_bundle", ["/ssl/notifynl.pem", None])
def test_send_data_to_service_callback_api_verifies_against_ca_bundle(notify_api, monkeypatch, ca_bundle):
    # requests swaps verify=True for these env vars, which would hide what we pass
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    callback_url = "https://callbacks.eindhoven.nl/notify"
    celery_task_mock = mock.MagicMock()
    celery_task_mock.name = "my-task-name"

    with set_config(notify_api, "SSL_CA_BUNDLE", ca_bundle), requests_mock.Mocker() as request_mock:
        request_mock.post(callback_url, json={}, status_code=200)
        _send_data_to_service_callback_api(celery_task_mock, {"id": "hello"}, callback_url, "my-token", "hello", {})

    assert request_mock.request_history[0].verify == (ca_bundle or True)
