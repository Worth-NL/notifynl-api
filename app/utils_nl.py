import os
from urllib.parse import urlparse

from flask import current_app


def get_client_certificate_path(url: str) -> str | None:
    """
    Return the client certificate to present for mutual TLS when calling `url`, or None if there isn't one.

    Certificates are looked up per hostname as `<hostname with dots replaced by dashes>.pem` in SSL_CERT_DIR (mounted
    from the `callback-mtls-certs` secret in notifynl-full); each file holds both the certificate and its private key.
    Hosts without their own certificate get SSL_DEFAULT_CLIENT_CERT, unless they are in
    SSL_DEFAULT_CLIENT_CERT_EXCLUDED_HOSTNAMES. A client certificate is only sent when the server asks for one.
    """
    hostname = urlparse(url).hostname
    if not hostname:
        return None

    certificate_dir = current_app.config.get("SSL_CERT_DIR")
    if certificate_dir:
        certificate_path = os.path.join(certificate_dir, f"{hostname.replace('.', '-')}.pem")
        if os.path.exists(certificate_path):
            _log_client_certificate("hostname", certificate_path, url)
            return certificate_path

    if hostname in (current_app.config.get("SSL_DEFAULT_CLIENT_CERT_EXCLUDED_HOSTNAMES") or ()):
        _log_client_certificate("excluded", None, url)
        return None

    default_certificate_path = current_app.config.get("SSL_DEFAULT_CLIENT_CERT")
    if default_certificate_path and os.path.exists(default_certificate_path):
        _log_client_certificate("default", default_certificate_path, url)
        return default_certificate_path

    return None


def get_ca_bundle() -> str | bool:
    """Return the CA bundle to verify server certificates against, for requests' `verify=`."""
    return current_app.config.get("SSL_CA_BUNDLE") or True


def _log_client_certificate(source: str, certificate_path: str | None, url: str):
    current_app.logger.info(
        "Client certificate [%s] (%s) selected for [%s].",
        certificate_path,
        source,
        url,
        extra={"client_certificate_source": source},
    )
