import json


def test_try_send_sms_lets_spryng_choose_the_encoding(mock_spryng_client, mocker):
    response = mocker.Mock(status_code=200, text="{}")
    mock_request = mocker.patch("app.clients.sms.spryng.request", return_value=response)

    mock_spryng_client.try_send_sms(
        to="+31612345678", content="Hallo", reference="ref", international=False, sender="NotifyNL"
    )

    payload = json.loads(mock_request.call_args.kwargs["data"])
    # "auto" keeps plain GSM messages at 160 chars/part; "unicode" would bill every message at 70 chars/part
    assert payload["encoding"] == "auto"
    assert payload["recipients"] == ["31612345678"]
