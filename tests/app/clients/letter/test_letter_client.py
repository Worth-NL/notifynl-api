import logging

import pytest

from app.clients.letter import (
    LetterClient,
    LetterClientNonRetryableException,
    LetterClientRetryableException,
    LetterSendResult,
)
from app.clients.letter.pingen import PingenClient
from app.clients.letter.rest_endpoint import RestEndpointLetterClient
from app.otel_metrics.provider import _request_duration


class FakeLetterClient(LetterClient):
    name = "fake"

    def __init__(self, current_app, outcome):
        super().__init__(current_app)
        self.outcome = outcome

    def try_send_letter(self, letter, letter_provider):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_send_letter_returns_the_result_and_logs_success(notify_api, letter, caplog):
    client = FakeLetterClient(notify_api, LetterSendResult(provider_reference="abc"))

    with caplog.at_level(logging.INFO):
        assert client.send_letter(letter, None) == LetterSendResult(provider_reference="abc")

    assert "Provider request for fake succeeded" in caplog.messages
    assert any(
        message.startswith(f"fake request for {letter.notification_id} finished in") for message in caplog.messages
    )


@pytest.mark.parametrize(
    "exception",
    [
        LetterClientRetryableException("down"),
        LetterClientNonRetryableException("rejected", "endpoint-http-400"),
    ],
)
def test_send_letter_logs_failure_and_reraises(notify_api, letter, exception, caplog):
    client = FakeLetterClient(notify_api, exception)

    with caplog.at_level(logging.INFO), pytest.raises(type(exception)):
        client.send_letter(letter, None)

    assert "Provider request for fake failed" in caplog.messages
    assert any(
        message.startswith(f"fake request for {letter.notification_id} finished in") for message in caplog.messages
    )


@pytest.mark.parametrize(
    "client_class, failing_step",
    [
        (PingenClient, "_request_file_upload"),
        (RestEndpointLetterClient, "_validate_url"),
    ],
)
def test_try_send_letter_records_the_request_duration(notify_api, mocker, letter, client_class, failing_step):
    record = mocker.patch.object(_request_duration, "record")
    mocker.patch.object(client_class, failing_step, side_effect=LetterClientRetryableException("down"))
    client = client_class(notify_api)

    with pytest.raises(LetterClientRetryableException):
        client.try_send_letter(letter, mocker.Mock(endpoint_url="https://example.com"))

    record.assert_called_once()
    attributes = record.call_args.args[1]
    assert attributes["notification.type"] == "letter"
    assert attributes["provider.name"] == client_class.name
    assert attributes["error.type"].endswith("LetterClientRetryableException")
