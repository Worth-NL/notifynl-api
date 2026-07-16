import base64

import pytest
from ebms_adapter_client.exceptions import EbmsBadRequestError, EbmsServerError
from flask import current_app

from app import signing
from app.clients.messagebox import MessageboxClientException, MessageboxClientNonRetryableException
from app.clients.messagebox.ebms_adapter import EbmsAdapterClient
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
        to_field=signing.encode("123456789"),
        personalisation={"message": "Hello & welcome", "subject": "Test subject"},
        status="created",
    )
    return notification


def _client(app, statsd_client=None):
    app.config["EBMS_BERICHTENBOX_CPA_ID"] = "MIJNOVERHEID-EBMS-BB-2-0_example"
    app.config["EBMS_BERICHTENBOX_FROM_PARTY_ID"] = FROM_PARTY_ID
    app.config["EBMS_BERICHTENBOX_TO_PARTY_ID"] = TO_PARTY_ID
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
