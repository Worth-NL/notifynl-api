import pytest

from app.clients.letter.pingen import PingenClient
from app.clients.letter.rest_endpoint import RestEndpointLetterClient
from app.letters_nl.provider import MissingTestLetterEndpoint, resolve_letter_provider
from app.letters_nl.test_endpoint import get_test_letter_endpoint, uses_test_letter_endpoint
from app.models_nl import OrganisationLetterProvider
from tests.app.db import create_notification, create_organisation, create_service, create_template
from tests.app.db_nl import create_organisation_letter_provider, create_organisation_test_letter_endpoint


def test_resolves_the_test_endpoint_for_a_test_key(notify_db_session):
    organisation = create_organisation()
    test_endpoint = create_organisation_test_letter_endpoint(organisation)

    client, resolved = resolve_letter_provider(organisation.id, test_key=True)

    assert isinstance(client, RestEndpointLetterClient)
    assert resolved == test_endpoint


def test_a_live_letter_never_resolves_the_test_endpoint(notify_db_session):
    organisation = create_organisation()
    create_organisation_test_letter_endpoint(organisation)

    client, resolved = resolve_letter_provider(organisation.id, test_key=False)

    assert isinstance(client, PingenClient)
    assert isinstance(resolved, OrganisationLetterProvider)


def test_a_live_letter_keeps_using_the_live_provider_when_there_is_a_test_endpoint(notify_db_session):
    organisation = create_organisation()
    letter_provider = create_organisation_letter_provider(
        organisation,
        "rest-endpoint",
        endpoint_url="https://print.example.com",
        auth_method="api_key",
        auth_config={"api_key_header": "X-Api-Key", "api_key": "k"},
    )
    create_organisation_test_letter_endpoint(organisation)

    _, resolved = resolve_letter_provider(organisation.id, test_key=False)

    assert resolved == letter_provider


def test_a_test_key_without_a_test_endpoint_fails_closed_and_never_uses_the_live_provider(notify_db_session):
    organisation = create_organisation()
    create_organisation_letter_provider(
        organisation,
        "rest-endpoint",
        endpoint_url="https://print.example.com",
        auth_method="api_key",
        auth_config={"api_key_header": "X-Api-Key", "api_key": "k"},
    )

    with pytest.raises(MissingTestLetterEndpoint):
        resolve_letter_provider(organisation.id, test_key=True)


def test_an_incomplete_test_endpoint_is_not_used(notify_db_session):
    organisation = create_organisation()
    create_organisation_test_letter_endpoint(organisation, auth_config={"api_key_header": "X-Api-Key"})

    assert get_test_letter_endpoint(organisation.id) is None
    with pytest.raises(MissingTestLetterEndpoint):
        resolve_letter_provider(organisation.id, test_key=True)


def test_no_test_endpoint_for_a_service_without_an_organisation(notify_db_session):
    assert get_test_letter_endpoint(None) is None


@pytest.mark.parametrize(
    "key_type, has_test_endpoint, expected",
    [
        ("test", True, True),
        ("test", False, False),
        ("normal", True, False),
        ("normal", False, False),
    ],
)
def test_only_test_letters_of_an_organisation_with_a_test_endpoint_use_it(
    notify_db_session, key_type, has_test_endpoint, expected
):
    organisation = create_organisation()
    if has_test_endpoint:
        create_organisation_test_letter_endpoint(organisation)
    service = create_service(organisation=organisation)
    template = create_template(service=service, template_type="letter")
    notification = create_notification(template=template, key_type=key_type)

    assert uses_test_letter_endpoint(notification) is expected
