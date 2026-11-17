from datetime import UTC, datetime

from app.status.security_txt_nl import SECURITY_TXT_EXPIRES


def test_security_txt_is_served_as_plain_text(client, notify_api):
    response = client.get("/.well-known/security.txt")

    assert response.status_code == 200
    assert response.content_type == "text/plain; charset=utf-8"
    assert response.get_data(as_text=True).splitlines() == [
        "Contact: mailto:info@worth.nl",
        f"Expires: {SECURITY_TXT_EXPIRES}",
        "Preferred-Languages: en, nl",
        "Policy: https://github.com/Worth-NL/notifynl-api/security/policy",
        f"Canonical: {notify_api.config['API_HOST_NAME']}/.well-known/security.txt",
    ]


def test_security_txt_expiry_is_in_the_future():
    expires = datetime.strptime(SECURITY_TXT_EXPIRES, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)

    assert expires > datetime.now(UTC)


def test_legacy_security_txt_redirects_to_well_known(client):
    response = client.get("/security.txt")

    assert response.status_code == 301
    assert response.location.endswith("/.well-known/security.txt")
