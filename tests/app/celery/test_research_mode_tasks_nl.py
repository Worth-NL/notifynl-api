import json
import uuid

import pytest
import requests
from flask import url_for
from freezegun import freeze_time

from app import signing
from app.celery.process_letter_client_response_tasks import process_letter_callback_data
from app.celery.research_mode_tasks import (
    _create_fake_letter_callback_data,
    create_fake_letter_callback,
    send_sms_response,
)
from app.constants import EUROPE, NETHERLANDS, REST_OF_WORLD
from app.notifications.notifications_letter_callback import dvla_letter_callback_schema
from app.schema_validation import validate


@freeze_time("2017-07-17T12:14:03.646")
def test_make_spryng_callback(notify_api, rmock):
    endpoint = "http://localhost:6011/notifications/sms/spryng"
    rmock.request("GET", endpoint, json={"result": "success"}, status_code=200)
    send_sms_response("spryng", "1234", "07700900001")

    assert rmock.called
    request = rmock.request_history[0]
    assert request.method == "GET"
    assert request.url.split("?")[0] == endpoint
    assert request.qs == {"status": ["10"], "reasoncode": ["0"], "reference": ["1234"]}


def test_spryng_callback_logs_on_api_call_failure(notify_api, rmock, caplog):
    endpoint = "http://localhost:6011/notifications/sms/spryng"
    rmock.request("GET", endpoint, json={"error": "not allowed"}, status_code=405)

    with pytest.raises(requests.HTTPError), caplog.at_level("ERROR"):
        send_sms_response("spryng", "1234", "07700900001")

    assert rmock.called
    assert "API GET request on http://localhost:6011/notifications/sms/spryng failed with status 405" in caplog.messages


@pytest.mark.parametrize(
    "postage, expected_mailing_product",
    [
        (NETHERLANDS, "UNSORTED"),
        (EUROPE, "INT EU"),
        (REST_OF_WORLD, "INT ROW"),
    ],
)
def test_fake_letter_callback_data_uses_nl_postage(postage, expected_mailing_product):
    data = _create_fake_letter_callback_data(uuid.uuid4(), 2, postage)

    validate(data, dvla_letter_callback_schema)
    despatch_properties = {prop["key"]: prop["value"] for prop in data["data"]["despatchProperties"]}
    assert despatch_properties["postageClass"] == postage
    assert despatch_properties["mailingProduct"] == expected_mailing_product
    assert despatch_properties["totalSheets"] == "2"


@pytest.mark.parametrize("legacy_postage", ["first", "second", "economy", None])
def test_fake_letter_callback_data_maps_legacy_postage_to_netherlands(legacy_postage):
    data = _create_fake_letter_callback_data(uuid.uuid4(), 1, legacy_postage)

    validate(data, dvla_letter_callback_schema)
    despatch_properties = {prop["key"]: prop["value"] for prop in data["data"]["despatchProperties"]}
    assert despatch_properties["postageClass"] == NETHERLANDS
    assert despatch_properties["mailingProduct"] == "UNSORTED"


@pytest.mark.parametrize("postage", [NETHERLANDS, EUROPE, REST_OF_WORLD])
def test_fake_letter_callback_data_is_accepted_by_letter_callback_route(client, mock_celery_task, postage):
    mock_task = mock_celery_task(process_letter_callback_data)
    notification_id = uuid.uuid4()

    response = client.post(
        url_for(
            "notifications_letter_callback.process_letter_callback",
            token=signing.encode(str(notification_id)),
        ),
        data=json.dumps(_create_fake_letter_callback_data(notification_id, 3, postage)),
    )

    assert response.status_code == 204, response.json
    assert mock_task.call_args.kwargs["kwargs"]["notification_id"] == notification_id
    assert mock_task.call_args.kwargs["kwargs"]["page_count"] == 3


@freeze_time("2024-07-26 16:30:53.321")
@pytest.mark.parametrize(
    "postage, response_mailing_product",
    [
        (NETHERLANDS, "UNSORTED"),
        (EUROPE, "INT EU"),
        (REST_OF_WORLD, "INT ROW"),
    ],
)
def test_create_fake_letter_callback_sends_letter_response(
    notify_api, sample_letter_notification, postage, response_mailing_product, rmock
):
    rmock.post(
        f"http://localhost:6011/notifications/letter/status?token={signing.encode(str(sample_letter_notification.id))}",
    )

    create_fake_letter_callback(sample_letter_notification.id, 2, postage)

    assert rmock.last_request.headers["Content-Type"] == "application/json"
    assert rmock.last_request.json()["data"]["despatchProperties"] == [
        {"key": "totalSheets", "value": "2"},
        {"key": "postageClass", "value": postage},
        {"key": "mailingProduct", "value": response_mailing_product},
        {"key": "productionRunDate", "value": "2024-07-26 16:30:53.321000"},
    ]
    assert rmock.last_request.json()["data"]["jobId"] == str(sample_letter_notification.id)
