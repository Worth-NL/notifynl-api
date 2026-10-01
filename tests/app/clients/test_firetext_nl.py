from unittest.mock import Mock
from urllib.parse import parse_qs

import pytest
import requests_mock

from app.clients.sms.firetext import FiretextClient


@pytest.fixture
def mock_firetext_configured_app():
    return Mock(
        config={
            "FIRETEXT_URL": "https://example.com/firetext",
            "FIRETEXT_API_KEY": "foo",
            "FIRETEXT_INTERNATIONAL_API_KEY": "international",
            "FROM_NUMBER": "bar",
        }
    )


def test_try_send_sms_lets_firetext_auto_detect_unicode(mock_firetext_configured_app):
    firetext_client = FiretextClient(mock_firetext_configured_app)

    with requests_mock.Mocker() as request_mock:
        request_mock.post("https://example.com/firetext", json={"code": 0}, status_code=200)
        firetext_client.try_send_sms("+31612345678", "Financiële gegevens uit België", "my reference", False, "bar")

    request_args = parse_qs(request_mock.request_history[0].text)
    # 2 = auto-detect; Firetext's default (0) is GSM-only, which can't carry ë/ï
    assert request_args["unicode"][0] == "2"
    assert request_args["message"][0] == "Financiële gegevens uit België"
