import logging
from unittest import mock

import pytest

from app.utils_nl import get_ca_bundle, get_client_certificate
from tests.conftest import set_config, set_config_values

EINDHOVEN_URL = "https://callbacks.eindhoven.nl/notify"


@pytest.fixture
def default_certificate(tmp_path):
    certificate = tmp_path / "default" / "client.pem"
    certificate.parent.mkdir()
    certificate.write_text("cert and key")
    return certificate


def test_get_client_certificate_returns_certificate_for_hostname(notify_api, tmp_path):
    certificate = tmp_path / "wsgateway-extern-denhaag-nl.pem"
    certificate.write_text("cert and key")

    with set_config(notify_api, "SSL_CERT_DIR", str(tmp_path)):
        client_certificate = get_client_certificate("https://wsgateway-extern.denhaag.nl/canon/syshub/v1/?a=b")

    assert client_certificate == (str(certificate), "hostname")


@pytest.mark.parametrize(
    "url",
    [
        "https://another-host.example.com/callback",
        "not a url",
    ],
)
def test_get_client_certificate_returns_none_without_matching_certificate(notify_api, tmp_path, url):
    (tmp_path / "wsgateway-extern-denhaag-nl.pem").write_text("cert and key")

    with set_config(notify_api, "SSL_CERT_DIR", str(tmp_path)):
        assert get_client_certificate(url) == (None, "none")


def test_get_client_certificate_returns_none_without_certificate_dir(notify_api):
    with set_config(notify_api, "SSL_CERT_DIR", None):
        assert get_client_certificate("https://wsgateway-extern.denhaag.nl/") == (None, "none")


@pytest.mark.parametrize("excluded_hostnames", [frozenset(), frozenset({"wsgateway-extern.denhaag.nl"})])
def test_get_client_certificate_prefers_hostname_certificate_over_default(
    notify_api, tmp_path, default_certificate, excluded_hostnames
):
    certificate = tmp_path / "wsgateway-extern-denhaag-nl.pem"
    certificate.write_text("cert and key")

    with set_config_values(
        notify_api,
        {
            "SSL_CERT_DIR": str(tmp_path),
            "SSL_DEFAULT_CLIENT_CERT": str(default_certificate),
            "SSL_DEFAULT_CLIENT_CERT_EXCLUDED_HOSTNAMES": excluded_hostnames,
        },
    ):
        assert get_client_certificate("https://wsgateway-extern.denhaag.nl/") == (str(certificate), "hostname")


@pytest.mark.parametrize("certificate_dir", [True, False])
def test_get_client_certificate_returns_default_certificate_without_hostname_certificate(
    notify_api, tmp_path, default_certificate, certificate_dir
):
    with set_config_values(
        notify_api,
        {
            "SSL_CERT_DIR": str(tmp_path) if certificate_dir else None,
            "SSL_DEFAULT_CLIENT_CERT": str(default_certificate),
            "SSL_DEFAULT_CLIENT_CERT_EXCLUDED_HOSTNAMES": frozenset({"hooks.vendor.example"}),
        },
    ):
        assert get_client_certificate(EINDHOVEN_URL) == (str(default_certificate), "default")


@pytest.mark.parametrize("url", ["https://hooks.vendor.example/callback", "https://Hooks.Vendor.Example:8443/callback"])
def test_get_client_certificate_returns_none_for_excluded_hostname(notify_api, tmp_path, default_certificate, url):
    with set_config_values(
        notify_api,
        {
            "SSL_CERT_DIR": str(tmp_path),
            "SSL_DEFAULT_CLIENT_CERT": str(default_certificate),
            "SSL_DEFAULT_CLIENT_CERT_EXCLUDED_HOSTNAMES": frozenset({"hooks.vendor.example"}),
        },
    ):
        assert get_client_certificate(url) == (None, "excluded")


def test_get_client_certificate_returns_none_when_default_certificate_is_missing(notify_api, tmp_path):
    with set_config_values(
        notify_api,
        {"SSL_CERT_DIR": str(tmp_path), "SSL_DEFAULT_CLIENT_CERT": str(tmp_path / "default" / "client.pem")},
    ):
        assert get_client_certificate(EINDHOVEN_URL) == (None, "none")


def _missing_default_certificate_warnings(caplog):
    return [message for message in caplog.messages if message.startswith("Default client certificate")]


def test_get_client_certificate_warns_once_when_default_certificate_is_missing(notify_api, tmp_path, caplog):
    default_certificate = tmp_path / "default" / "client.pem"

    with (
        set_config_values(
            notify_api, {"SSL_CERT_DIR": str(tmp_path), "SSL_DEFAULT_CLIENT_CERT": str(default_certificate)}
        ),
        caplog.at_level(logging.WARNING),
    ):
        get_client_certificate(EINDHOVEN_URL)
        get_client_certificate(EINDHOVEN_URL)

    assert _missing_default_certificate_warnings(caplog) == [
        f"Default client certificate [{default_certificate}] does not exist, "
        "so hosts without their own certificate get none."
    ]


def test_get_client_certificate_finds_default_certificate_created_later(notify_api, tmp_path):
    default_certificate = tmp_path / "client.pem"

    with set_config_values(
        notify_api, {"SSL_CERT_DIR": str(tmp_path), "SSL_DEFAULT_CLIENT_CERT": str(default_certificate)}
    ):
        assert get_client_certificate(EINDHOVEN_URL) == (None, "none")
        default_certificate.write_text("cert and key")
        assert get_client_certificate(EINDHOVEN_URL) == (str(default_certificate), "default")


@pytest.mark.parametrize(
    "default_certificate_name, excluded_hostnames",
    [(None, frozenset()), ("missing.pem", frozenset({"callbacks.eindhoven.nl"}))],
    ids=["not configured", "excluded host"],
)
def test_get_client_certificate_does_not_warn_when_default_certificate_would_not_be_used(
    notify_api, tmp_path, caplog, default_certificate_name, excluded_hostnames
):
    with (
        set_config_values(
            notify_api,
            {
                "SSL_CERT_DIR": str(tmp_path),
                "SSL_DEFAULT_CLIENT_CERT": default_certificate_name and str(tmp_path / default_certificate_name),
                "SSL_DEFAULT_CLIENT_CERT_EXCLUDED_HOSTNAMES": excluded_hostnames,
            },
        ),
        caplog.at_level(logging.WARNING),
    ):
        get_client_certificate(EINDHOVEN_URL)

    assert not _missing_default_certificate_warnings(caplog)


@pytest.mark.parametrize("unset", ["absent", None])
def test_get_client_certificate_without_default_certificate_settings(notify_api, tmp_path, unset):
    # tests run on the upstream Test config, which lacks ConfigNL's settings; set_config restores them as None
    with mock.patch.dict(notify_api.config, {"SSL_CERT_DIR": str(tmp_path)}):
        for key in ("SSL_DEFAULT_CLIENT_CERT", "SSL_DEFAULT_CLIENT_CERT_EXCLUDED_HOSTNAMES"):
            if unset == "absent":
                notify_api.config.pop(key, None)
            else:
                notify_api.config[key] = None

        assert get_client_certificate(EINDHOVEN_URL) == (None, "none")


@pytest.mark.parametrize("ca_bundle, expected", [("/ssl/notifynl.pem", "/ssl/notifynl.pem"), (None, True)])
def test_get_ca_bundle(notify_api, ca_bundle, expected):
    with set_config(notify_api, "SSL_CA_BUNDLE", ca_bundle):
        assert get_ca_bundle() == expected
