import pytest

from app.clients.letter.pingen import PingenClient
from app.clients.letter.rest_endpoint import RestEndpointLetterClient
from app.letters_nl.provider import resolve_letter_provider
from tests.app.db import create_organisation
from tests.app.db_nl import create_organisation_letter_provider

API_KEY = {"api_key_header": "X-Api-Key", "api_key": "k"}


def test_resolves_a_completely_configured_rest_endpoint(notify_db_session):
    organisation = create_organisation()
    letter_provider = create_organisation_letter_provider(
        organisation,
        "rest-endpoint",
        endpoint_url="https://print.example.com",
        auth_method="api_key",
        auth_config=API_KEY,
    )

    client, resolved = resolve_letter_provider(organisation.id)

    assert isinstance(client, RestEndpointLetterClient)
    assert resolved == letter_provider


def test_resolves_pingen_when_the_organisation_chose_it(notify_db_session):
    organisation = create_organisation()
    letter_provider = create_organisation_letter_provider(organisation, "pingen")

    client, resolved = resolve_letter_provider(organisation.id)

    assert isinstance(client, PingenClient)
    assert resolved == letter_provider


def test_falls_back_to_pingen_without_a_letter_provider(notify_db_session):
    client, resolved = resolve_letter_provider(create_organisation().id)

    assert isinstance(client, PingenClient)
    assert resolved is None


@pytest.mark.parametrize(
    "endpoint_url, auth_config, undecryptable",
    [
        (None, API_KEY, False),
        ("https://print.example.com", None, False),
        ("https://print.example.com", API_KEY, True),
    ],
)
def test_falls_back_to_pingen_for_an_incomplete_rest_endpoint(
    notify_db_session, caplog, endpoint_url, auth_config, undecryptable
):
    organisation = create_organisation()
    letter_provider = create_organisation_letter_provider(
        organisation, "rest-endpoint", endpoint_url=endpoint_url, auth_method="api_key", auth_config=auth_config
    )
    if undecryptable:
        letter_provider._auth_config = "not-a-fernet-token"

    with caplog.at_level("WARNING"):
        client, resolved = resolve_letter_provider(organisation.id)

    assert isinstance(client, PingenClient)
    assert resolved is None
    assert "is not completely configured, sending with pingen instead" in caplog.text
