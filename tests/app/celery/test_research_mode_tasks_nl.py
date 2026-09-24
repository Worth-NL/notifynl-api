import pytest
import requests
from freezegun import freeze_time

from app.celery.research_mode_tasks import send_sms_response


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
