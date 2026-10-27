import socket

import pytest
import requests
from urllib3.exceptions import MaxRetryError, NameResolutionError, NewConnectionError, ProtocolError

from app.clients.letter import Letter

# requests errors as raised for a failure to connect, which means the provider never got the request ...
FAILED_TO_CONNECT = {
    "connection-refused": requests.ConnectionError(
        MaxRetryError(None, "/", NewConnectionError(None, "Connection refused"))
    ),
    "dns": requests.ConnectionError(MaxRetryError(None, "/", NameResolutionError("print.example.com", None, "nope"))),
    "connect-timeout": requests.ConnectTimeout(MaxRetryError(None, "/", NewConnectionError(None, "timed out"))),
}
# ... and for failures after the request went out, which the provider may have acted on
FAILED_AFTER_SENDING = {
    "read-timeout": requests.ReadTimeout("Read timed out."),
    "connection-closed": requests.ConnectionError(ProtocolError("Connection aborted.")),
    "chunked-encoding": requests.exceptions.ChunkedEncodingError("Connection broken"),
}


@pytest.fixture
def public_dns(mocker):
    return mocker.patch(
        "app.letters_nl.url_validation.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )


@pytest.fixture
def letter():
    return Letter(
        notification_id="7b2dd5d6-b52f-4a9c-9d0e-9d3b4b1b4a51",
        reference="ABCDEFGHIJKL",
        organisation_id="9d0c6c4a-5a5e-4c7a-9f7e-3c2d1b0a9f8e",
        pdf=b"%PDF-1.7 letter",
        postage="netherlands",
        callback_url="https://api.notifynl.nl/notifications/letter/provider-status?token=signed",
    )
