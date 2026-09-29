import os
from urllib.parse import urlparse

from flask import current_app


def get_client_certificate_path(url: str) -> str | None:
    """
    Return the client certificate to present for mutual TLS when calling `url`, or None if there isn't one.

    Certificates are looked up per hostname as `<hostname with dots replaced by dashes>.pem` in SSL_CERT_DIR (mounted
    from the `callback-mtls-certs` secret in notifynl-full); each file holds both the certificate and its private key.
    """
    certificate_dir = current_app.config.get("SSL_CERT_DIR")
    hostname = urlparse(url).hostname
    if not certificate_dir or not hostname:
        return None

    certificate_name = f"{hostname.replace('.', '-')}.pem"
    certificate_path = os.path.join(certificate_dir, certificate_name)
    if not os.path.exists(certificate_path):
        return None

    current_app.logger.info("Certificate [%s] found for [%s], using as client certificate.", certificate_name, url)
    return certificate_path
