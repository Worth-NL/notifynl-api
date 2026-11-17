from app.dao.organisation_dao import dao_create_organisation
from app.dao.organisation_letter_provider_dao import dao_get_organisation_letter_provider
from app.letters_nl.constants import LETTER_PROVIDER_PINGEN
from app.models import Organisation


def test_dao_create_organisation_gives_it_pingen_as_letter_provider(notify_db_session):
    organisation = Organisation(name="Gemeente Nieuw", active=True)

    dao_create_organisation(organisation)

    letter_provider = dao_get_organisation_letter_provider(organisation.id)
    assert letter_provider.provider.identifier == LETTER_PROVIDER_PINGEN
    assert letter_provider.address_placement == "60mm"
    assert letter_provider.endpoint_url is None
    assert letter_provider.has_credentials is False


def test_create_organisation_endpoint_gives_it_pingen_as_letter_provider(admin_request, notify_db_session):
    response = admin_request.post(
        "organisation.create_organisation",
        _data={"name": "Gemeente Nieuw", "active": True, "crown": False, "organisation_type": "local"},
        _expected_status=201,
    )

    assert dao_get_organisation_letter_provider(response["id"]).provider.identifier == LETTER_PROVIDER_PINGEN
