from werkzeug.datastructures import Authorization

from app.celery.process_sms_client_response_tasks import process_sms_client_response
from app.hashing import hashpw

DATA = "mobile=31612345678&status=0&reference=notification_id&time=2016-03-10 14:17:00"


def _post(client, headers):
    return client.post(
        path="/notifications/sms/firetext",
        data=DATA,
        headers=[("Content-Type", "application/x-www-form-urlencoded"), *headers],
    )


def test_firetext_callback_without_auth_is_accepted_and_logged(client, mock_celery_task, caplog):
    mock_celery = mock_celery_task(process_sms_client_response)

    response = _post(client, headers=[])

    assert response.status_code == 200
    mock_celery.assert_called_once()
    assert any("Suppressing basic auth failure" in r.message for r in caplog.records)


def test_firetext_callback_with_wrong_auth_is_still_accepted(client, mock_celery_task):
    client.application.config["FIRETEXT_DELIVERY_STATUS_CALLBACK_ALLOWED_BASIC_AUTH_CREDENTIALS"] = {
        "foo123": hashpw("bar123"),
    }
    mock_celery = mock_celery_task(process_sms_client_response)

    response = _post(
        client, headers=[("Authorization", Authorization("basic", {"username": "foo123", "password": "x"}))]
    )

    assert response.status_code == 200
    mock_celery.assert_called_once()
