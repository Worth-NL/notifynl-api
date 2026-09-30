import pytest

from app.utils_nl import get_client_certificate_path
from tests.conftest import set_config


def test_get_client_certificate_path_returns_certificate_for_hostname(notify_api, tmp_path):
    certificate = tmp_path / "wsgateway-extern-denhaag-nl.pem"
    certificate.write_text("cert and key")

    with set_config(notify_api, "SSL_CERT_DIR", str(tmp_path)):
        path = get_client_certificate_path("https://wsgateway-extern.denhaag.nl/canon/syshub/v1/?a=b")

    assert path == str(certificate)


@pytest.mark.parametrize(
    "url",
    [
        "https://another-host.example.com/callback",
        "not a url",
    ],
)
def test_get_client_certificate_path_returns_none_without_matching_certificate(notify_api, tmp_path, url):
    (tmp_path / "wsgateway-extern-denhaag-nl.pem").write_text("cert and key")

    with set_config(notify_api, "SSL_CERT_DIR", str(tmp_path)):
        assert get_client_certificate_path(url) is None


def test_get_client_certificate_path_returns_none_without_certificate_dir(notify_api):
    with set_config(notify_api, "SSL_CERT_DIR", None):
        assert get_client_certificate_path("https://wsgateway-extern.denhaag.nl/") is None
