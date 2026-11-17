"""
Real TLS handshakes against a local server, for the default client certificate in app.utils_nl.

Each test starts its own HTTPServer instead of using the session-scoped `httpserver` fixture: the server's SSL context
differs per test, and tests/app/clients/test_dvla.py already overrides `httpserver_ssl_context` for its own server.
"""

import ssl

import pytest
import requests
import trustme
from pytest_httpserver import HTTPServer

from app.utils_nl import get_ca_bundle, get_client_certificate
from tests.conftest import set_config_values


@pytest.fixture(scope="module")
def server_ca():
    return trustme.CA()


@pytest.fixture(scope="module")
def g4_ca():
    # stands in for PKIoverheid G4, which issued NotifyNL's default client certificate
    return trustme.CA()


@pytest.fixture(scope="module")
def other_ca():
    return trustme.CA()


@pytest.fixture
def tls_config(tmp_path, server_ca, g4_ca):
    default_certificate = tmp_path / "default" / "client.pem"
    default_certificate.parent.mkdir()
    g4_ca.issue_cert("notifynl.example").private_key_and_cert_chain_pem.write_to_path(str(default_certificate))
    ca_bundle = tmp_path / "ca-bundle.pem"
    server_ca.cert_pem.write_to_path(str(ca_bundle))
    return {
        "SSL_CERT_DIR": str(tmp_path),
        "SSL_DEFAULT_CLIENT_CERT": str(default_certificate),
        "SSL_DEFAULT_CLIENT_CERT_EXCLUDED_HOSTNAMES": frozenset(),
        "SSL_CA_BUNDLE": str(ca_bundle),
    }


@pytest.fixture
def start_server(server_ca):
    servers = []

    def _start_server(verify_mode, client_ca=None):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ca.issue_cert("localhost").configure_cert(context)
        context.verify_mode = verify_mode
        if client_ca:
            client_ca.configure_trust(context)

        server = HTTPServer(host="localhost", port=0, ssl_context=context)
        server.expect_request("/callback").respond_with_data("ok")
        server.start()
        servers.append(server)
        return server.url_for("/callback")

    yield _start_server

    for server in servers:
        server.stop()


def _post(url):
    return requests.post(url, cert=get_client_certificate(url).path, verify=get_ca_bundle(), timeout=5)


def test_default_certificate_is_presented_to_a_server_that_requires_it(notify_api, tls_config, start_server, g4_ca):
    url = start_server(ssl.CERT_REQUIRED, client_ca=g4_ca)

    with set_config_values(notify_api, tls_config):
        assert _post(url).status_code == 200


def test_default_certificate_does_not_affect_a_server_that_does_not_ask_for_one(notify_api, tls_config, start_server):
    url = start_server(ssl.CERT_NONE)

    with set_config_values(notify_api, tls_config):
        assert _post(url).status_code == 200


def test_default_certificate_fails_on_a_server_that_asks_optionally_and_rejects_it(
    notify_api, tls_config, start_server, other_ca
):
    # like nginx's `ssl_verify_client optional` with a CA list that doesn't include G4
    url = start_server(ssl.CERT_OPTIONAL, client_ca=other_ca)

    # TLS 1.3 clients see the rejection after the handshake, as an SSLError or a reset (both ConnectionErrors)
    with set_config_values(notify_api, tls_config), pytest.raises(requests.exceptions.ConnectionError):
        _post(url)


def test_excluded_hostname_sends_no_certificate_to_a_server_that_would_reject_it(
    notify_api, tls_config, start_server, other_ca
):
    url = start_server(ssl.CERT_OPTIONAL, client_ca=other_ca)

    with set_config_values(notify_api, {**tls_config, "SSL_DEFAULT_CLIENT_CERT_EXCLUDED_HOSTNAMES": {"localhost"}}):
        assert _post(url).status_code == 200
