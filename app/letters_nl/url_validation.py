import ipaddress
import socket
from urllib.parse import urlsplit

from flask import current_app


class InvalidLetterEndpointUrl(Exception):
    pass


def validate_letter_endpoint_url(url: str) -> None:
    """
    Guard against SSRF: organisation admins choose where their letter PDFs (and OAuth credentials) are POSTed, from
    inside our cluster. Only https URLs whose host resolves exclusively to public addresses are allowed. Checked when
    the URL is saved and again before every send, as DNS can change in between.

    LETTER_ENDPOINT_ALLOW_INSECURE (local development only) allows http and private hosts, for the local stub.
    """
    allow_insecure = current_app.config.get("LETTER_ENDPOINT_ALLOW_INSECURE", False)
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as e:
        raise InvalidLetterEndpointUrl(f"{url} is not a valid URL") from e

    if parts.scheme != "https" and not (allow_insecure and parts.scheme == "http"):
        raise InvalidLetterEndpointUrl(f"{url} must use https")
    if not parts.hostname:
        raise InvalidLetterEndpointUrl(f"{url} has no host")
    if parts.username or parts.password:
        raise InvalidLetterEndpointUrl(f"{url} must not contain credentials")
    if allow_insecure:
        return

    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, port or 443, type=socket.SOCK_STREAM)}
    except (socket.gaierror, UnicodeError) as e:
        raise InvalidLetterEndpointUrl(f"The host of {url} cannot be resolved") from e

    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise InvalidLetterEndpointUrl(f"{url} must not point to a private or internal address")
