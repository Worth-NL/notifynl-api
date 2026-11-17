import socket

import pytest

from app.letters_nl.url_validation import InvalidLetterEndpointUrl, validate_letter_endpoint_url
from tests.conftest import set_config


def _resolves_to(mocker, *addresses):
    return mocker.patch(
        "app.letters_nl.url_validation.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
            for address in addresses
        ],
    )


def test_https_url_resolving_to_public_addresses_is_valid(notify_api, mocker):
    getaddrinfo = _resolves_to(mocker, "93.184.216.34", "2606:2800:220:1::1")

    validate_letter_endpoint_url("https://print.example.com:8443/letters?x=1")

    getaddrinfo.assert_called_once_with("print.example.com", 8443, type=socket.SOCK_STREAM)


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",  # cloud metadata endpoint
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",
        "::1",
        "fd00::1",
        "fe80::1%eth0",
        "::ffff:10.0.0.1",
    ],
)
def test_url_resolving_to_a_private_or_internal_address_is_invalid(notify_api, mocker, address):
    _resolves_to(mocker, address)

    with pytest.raises(InvalidLetterEndpointUrl, match="must not point to a private or internal address"):
        validate_letter_endpoint_url("https://print.example.com/letters")


def test_url_resolving_to_any_private_address_is_invalid(notify_api, mocker):
    _resolves_to(mocker, "93.184.216.34", "10.0.0.5")

    with pytest.raises(InvalidLetterEndpointUrl, match="private or internal"):
        validate_letter_endpoint_url("https://print.example.com/letters")


@pytest.mark.parametrize(
    "url, message",
    [
        ("http://print.example.com/letters", "must use https"),
        ("ftp://print.example.com/letters", "must use https"),
        ("print.example.com/letters", "must use https"),
        ("https:///letters", "has no host"),
        ("https://user:pass@print.example.com/letters", "must not contain credentials"),
        ("https://print.example.com:99999/letters", "is not a valid URL"),
    ],
)
def test_malformed_or_insecure_url_is_invalid_without_resolving_it(notify_api, mocker, url, message):
    getaddrinfo = _resolves_to(mocker, "93.184.216.34")

    with pytest.raises(InvalidLetterEndpointUrl, match=message):
        validate_letter_endpoint_url(url)

    assert not getaddrinfo.called


def test_unresolvable_host_is_invalid(notify_api, mocker):
    mocker.patch("app.letters_nl.url_validation.socket.getaddrinfo", side_effect=socket.gaierror("no such host"))

    with pytest.raises(InvalidLetterEndpointUrl, match="cannot be resolved"):
        validate_letter_endpoint_url("https://nope.example.com/letters")


def test_insecure_urls_are_allowed_for_local_development(notify_api, mocker):
    getaddrinfo = _resolves_to(mocker, "127.0.0.1")

    with set_config(notify_api, "LETTER_ENDPOINT_ALLOW_INSECURE", True):
        validate_letter_endpoint_url("http://localhost:6300/letter-endpoint")

    assert not getaddrinfo.called
