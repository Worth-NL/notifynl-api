import base64

import pytest
from ebms_adapter_client.exceptions import EbmsBadRequestError, EbmsServerError
from flask import current_app

from app import encryption
from app.clients.messagebox import MessageboxClientException, MessageboxClientNonRetryableException
from app.clients.messagebox.ebms_adapter import (
    EbmsAdapterClient,
    get_messagebox_failure_reason,
    get_messagebox_responses,
)
from app.constants import MESSAGEBOX_TYPE
from app.dao.templates_messagebox_dao import get_messagebox_template
from tests.app.db import create_notification, create_service

# Synthetic placeholder OINs (not real CPA values). CLIENT_ORG_OIN is
# deliberately distinct from the configured from/to party ids below, to
# prove fromPartyId no longer varies with the client organisation's own OIN.
CLIENT_ORG_OIN = "33333333333333333333"
FROM_PARTY_ID = "11111111111111111111"
TO_PARTY_ID = "22222222222222222222"


@pytest.fixture
def messagebox_notification(notify_db_session, notify_user):
    service = create_service(service_permissions=[MESSAGEBOX_TYPE])
    service.oin = CLIENT_ORG_OIN
    template = get_messagebox_template(service.id)
    notification = create_notification(
        template=template,
        to_field=encryption.encrypt("123456789"),
        personalisation={"message": "Hello & welcome", "subject": "Test subject"},
        status="created",
    )
    return notification


def _client(app, statsd_client=None):
    app.config["EBMS_BERICHTENBOX_CPA_ID"] = "MIJNOVERHEID-EBMS-BB-2-0_example"
    app.config["EBMS_BERICHTENBOX_FROM_PARTY_ID"] = FROM_PARTY_ID
    app.config["EBMS_BERICHTENBOX_TO_PARTY_ID"] = TO_PARTY_ID
    app.config["EBMS_BERICHTENBOX_MESSAGE_TYPE"] = "test-123"
    app.config.setdefault("EBMS_ADAPTER_URL", "http://localhost:8080")
    return EbmsAdapterClient(app, statsd_client)


def test_init_accepts_current_app_and_statsd_client(mocker):
    statsd_client = mocker.Mock()
    client = _client(current_app._get_current_object(), statsd_client)
    assert client.current_app is current_app._get_current_object()
    assert client.statsd_client is statsd_client
    assert client.url == "http://localhost:8080"


def test_try_send_messagebox_builds_and_sends_message_request(mocker, messagebox_notification):
    mocker.patch("app.messagebox.utils.get_messagebox_attachments", return_value=[])
    mock_core_client = mocker.Mock()
    mock_core_client.send_message.return_value = "envelope-message-id-123"
    mock_core_client.__enter__ = mocker.Mock(return_value=mock_core_client)
    mock_core_client.__exit__ = mocker.Mock(return_value=False)
    mocker.patch("app.clients.messagebox.ebms_adapter.EbmsCoreClient", return_value=mock_core_client)

    client = _client(current_app._get_current_object(), mocker.Mock())

    result = client.try_send_messagebox(str(messagebox_notification.id))

    assert result == "envelope-message-id-123"
    mock_core_client.send_message.assert_called_once()
    message_request = mock_core_client.send_message.call_args[0][0]
    payload = message_request.to_dict()
    assert payload["properties"]["cpaId"] == "MIJNOVERHEID-EBMS-BB-2-0_example"
    # fromPartyId/toPartyId are the fixed CPA parties (Worth/Logius) -- they
    # must NOT vary with the client organisation's own OIN (CLIENT_ORG_OIN).
    assert payload["properties"]["fromPartyId"] == f"urn:osb:oin:{FROM_PARTY_ID}"
    assert payload["properties"]["toPartyId"] == f"urn:osb:oin:{TO_PARTY_ID}"
    assert payload["dataSources"][0]["contentId"] == str(messagebox_notification.id)

    # The client organisation's OIN and the recipient's BSN still travel
    # correctly in the message body (BerichtLeverancierID / GebruikerID),
    # independent of the now-fixed envelope party ids.
    xml_content = base64.b64decode(payload["dataSources"][0]["content"]).decode("utf-8")
    assert CLIENT_ORG_OIN in xml_content
    assert "123456789" in xml_content
    # No message_type key in personalisation -- falls back to the configured
    # EBMS_BERICHTENBOX_MESSAGE_TYPE ("test-123" here).
    assert "<bericht:BerichtType>test-123</bericht:BerichtType>" in xml_content
    # 0 attachments (mocked above) -- no Bijlagen element should be emitted.
    assert "Bijlagen" not in xml_content

    # notifynl-api reuses the notification id as both BatchID and BerichtID (one
    # notification == one batch always), so messagebox_scheduled_tasks can fall back to
    # BatchID when Logius echoes back a nil BerichtID -- see MESSAGEBOX_NIL_BERICHT_ID.
    notification_id = str(messagebox_notification.id)
    assert f"<BatchID>{notification_id}</BatchID>" in xml_content
    assert f"<bericht:BatchID>{notification_id}</bericht:BatchID>" in xml_content
    assert f"<bericht:BerichtID>{notification_id}</bericht:BerichtID>" in xml_content


def test_try_send_messagebox_uses_personalisation_message_type_override(mocker, notify_db_session, notify_user):
    mocker.patch("app.messagebox.utils.get_messagebox_attachments", return_value=[])
    mock_core_client = mocker.Mock()
    mock_core_client.send_message.return_value = "envelope-message-id-123"
    mock_core_client.__enter__ = mocker.Mock(return_value=mock_core_client)
    mock_core_client.__exit__ = mocker.Mock(return_value=False)
    mocker.patch("app.clients.messagebox.ebms_adapter.EbmsCoreClient", return_value=mock_core_client)

    service = create_service(service_permissions=[MESSAGEBOX_TYPE])
    service.oin = CLIENT_ORG_OIN
    template = get_messagebox_template(service.id)
    notification = create_notification(
        template=template,
        to_field=encryption.encrypt("123456789"),
        personalisation={"message": "Hello & welcome", "subject": "Test subject", "message_type": "custom-type"},
        status="created",
    )

    client = _client(current_app._get_current_object(), mocker.Mock())
    client.try_send_messagebox(str(notification.id))

    message_request = mock_core_client.send_message.call_args[0][0]
    xml_content = base64.b64decode(message_request.to_dict()["dataSources"][0]["content"]).decode("utf-8")
    # personalisation's message_type overrides the configured
    # EBMS_BERICHTENBOX_MESSAGE_TYPE ("test-123", set by _client).
    assert "<bericht:BerichtType>custom-type</bericht:BerichtType>" in xml_content


def test_try_send_messagebox_wraps_bad_request_as_non_retryable(mocker, messagebox_notification):
    mocker.patch("app.messagebox.utils.get_messagebox_attachments", return_value=[])
    mock_core_client = mocker.Mock()
    mock_core_client.send_message.side_effect = EbmsBadRequestError("bad payload")
    mock_core_client.__enter__ = mocker.Mock(return_value=mock_core_client)
    mock_core_client.__exit__ = mocker.Mock(return_value=False)
    mocker.patch("app.clients.messagebox.ebms_adapter.EbmsCoreClient", return_value=mock_core_client)

    client = _client(current_app._get_current_object(), mocker.Mock())

    with pytest.raises(MessageboxClientNonRetryableException):
        client.try_send_messagebox(str(messagebox_notification.id))


def test_try_send_messagebox_wraps_server_error_as_retryable(mocker, messagebox_notification):
    mocker.patch("app.messagebox.utils.get_messagebox_attachments", return_value=[])
    mock_core_client = mocker.Mock()
    mock_core_client.send_message.side_effect = EbmsServerError("boom")
    mock_core_client.__enter__ = mocker.Mock(return_value=mock_core_client)
    mock_core_client.__exit__ = mocker.Mock(return_value=False)
    mocker.patch("app.clients.messagebox.ebms_adapter.EbmsCoreClient", return_value=mock_core_client)

    client = _client(current_app._get_current_object(), mocker.Mock())

    with pytest.raises(MessageboxClientException):
        client.try_send_messagebox(str(messagebox_notification.id))


def test_get_messagebox_responses_maps_status_and_reason():
    status, reason = get_messagebox_responses("20", "OinInCPAKomtNietOvereenMetOinInBericht")
    assert status == "permanent-failure"
    assert reason == "OIN uit CPA komt niet overeen met OID in het bericht"


def test_get_messagebox_responses_reason_none_for_unknown_code():
    status, reason = get_messagebox_responses("10", "SomeUnknownCode")
    assert status == "delivered"
    assert reason is None


def test_get_messagebox_failure_reason_known_code():
    assert (
        get_messagebox_failure_reason("OinInCPAKomtNietOvereenMetOinInBericht")
        == "OIN uit CPA komt niet overeen met OID in het bericht"
    )


def test_get_messagebox_failure_reason_matches_across_status_entries():
    # Verwerkt is nested under the "10" entry, not "20" -- confirms the
    # helper searches every status entry's reasoncode, not just one.
    assert get_messagebox_failure_reason("Verwerkt") == "No error"


@pytest.mark.parametrize("code", [None, "", "SomeUnknownCode"])
def test_get_messagebox_failure_reason_none_for_unknown_or_absent_code(code):
    assert get_messagebox_failure_reason(code) is None
