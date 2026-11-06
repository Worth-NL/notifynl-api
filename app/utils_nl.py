import os
from functools import cache
from typing import NamedTuple
from urllib.parse import urlparse

from flask import current_app


class ClientCertificate(NamedTuple):
    path: str | None
    source: str  # "hostname", "excluded", "default" or "none"; callers put it on their own log lines


def get_client_certificate(url: str) -> ClientCertificate:
    """
    Return the client certificate to present for mutual TLS when calling `url`, and where it came from.

    Certificates are looked up per hostname as `<hostname with dots replaced by dashes>.pem` in SSL_CERT_DIR (mounted
    from the `callback-mtls-certs` secret in notifynl-full); each file holds both the certificate and its private key.
    Hosts without their own certificate get SSL_DEFAULT_CLIENT_CERT, unless they are in
    SSL_DEFAULT_CLIENT_CERT_EXCLUDED_HOSTNAMES. A client certificate is only sent when the server asks for one.
    """
    hostname = urlparse(url).hostname
    if not hostname:
        return ClientCertificate(None, "none")

    certificate_dir = current_app.config.get("SSL_CERT_DIR")
    if certificate_dir:
        certificate_path = os.path.join(certificate_dir, f"{hostname.replace('.', '-')}.pem")
        if os.path.exists(certificate_path):
            return ClientCertificate(certificate_path, "hostname")

    if hostname in (current_app.config.get("SSL_DEFAULT_CLIENT_CERT_EXCLUDED_HOSTNAMES") or ()):
        return ClientCertificate(None, "excluded")

    default_certificate_path = current_app.config.get("SSL_DEFAULT_CLIENT_CERT")
    if default_certificate_path:
        # checked on every call: the chart mounts this key as optional, so it can appear without a restart
        if os.path.exists(default_certificate_path):
            return ClientCertificate(default_certificate_path, "default")
        _warn_missing_default_certificate(default_certificate_path)

    return ClientCertificate(None, "none")


def get_ca_bundle() -> str | bool:
    """Return the CA bundle to verify server certificates against, for requests' `verify=`."""
    return current_app.config.get("SSL_CA_BUNDLE") or True


@cache
def _warn_missing_default_certificate(certificate_path: str) -> None:
    # cached to warn once per process instead of on every request
    current_app.logger.warning(
        "Default client certificate [%s] does not exist, so hosts without their own certificate get none.",
        certificate_path,
    )
