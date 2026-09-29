import pytest

from app.clients.letter import (
    LetterClient,
    LetterClientNonRetryableException,
    LetterClientRetryableException,
    LetterSendResult,
)


class FakeLetterClient(LetterClient):
    name = "fake"

    def __init__(self, current_app, statsd_client, outcome):
        super().__init__(current_app, statsd_client)
        self.outcome = outcome

    def try_send_letter(self, letter, letter_provider):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_send_letter_returns_the_result_and_records_success(notify_api, statsd_client, letter):
    client = FakeLetterClient(notify_api, statsd_client, LetterSendResult(provider_reference="abc"))

    assert client.send_letter(letter, None) == LetterSendResult(provider_reference="abc")

    statsd_client.incr.assert_called_once_with("clients.fake.success")
    assert statsd_client.timing.call_args.args[0] == "clients.fake.request-time"


@pytest.mark.parametrize(
    "exception",
    [
        LetterClientRetryableException("down"),
        LetterClientNonRetryableException("rejected", "endpoint-http-400"),
    ],
)
def test_send_letter_records_failure_and_reraises(notify_api, statsd_client, letter, exception):
    client = FakeLetterClient(notify_api, statsd_client, exception)

    with pytest.raises(type(exception)):
        client.send_letter(letter, None)

    statsd_client.incr.assert_called_once_with("clients.fake.error")
    assert statsd_client.timing.call_args.args[0] == "clients.fake.request-time"
