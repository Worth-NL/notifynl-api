import socket
from unittest import mock

import pytest

from app.clients.letter import Letter


@pytest.fixture
def statsd_client():
    return mock.Mock()


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
