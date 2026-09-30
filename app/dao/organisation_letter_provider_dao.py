from app import db, redis_store
from app.dao.dao_utils import autocommit
from app.dao.provider_details_dao import get_provider_details_by_identifier
from app.letters_nl.constants import LETTER_PROVIDER_PINGEN, PINGEN_ADDRESS_PLACEMENT
from app.models import Service
from app.models_nl import OrganisationLetterProvider


def add_default_letter_provider(organisation) -> None:
    """A new organisation sends its letters with Pingen until it chooses its own letter provider."""
    organisation.letter_provider = OrganisationLetterProvider(
        provider_details_id=get_provider_details_by_identifier(LETTER_PROVIDER_PINGEN).id,
        address_placement=PINGEN_ADDRESS_PLACEMENT,
    )


def dao_get_organisation_letter_provider(organisation_id) -> OrganisationLetterProvider | None:
    return OrganisationLetterProvider.query.filter_by(organisation_id=organisation_id).one_or_none()


@autocommit
def dao_set_organisation_letter_provider(
    organisation_id,
    *,
    provider_identifier,
    endpoint_url,
    auth_method,
    auth_config,
    address_placement,
    updated_by_id,
) -> OrganisationLetterProvider:
    letter_provider = dao_get_organisation_letter_provider(organisation_id) or OrganisationLetterProvider(
        organisation_id=organisation_id
    )
    letter_provider.provider_details_id = get_provider_details_by_identifier(provider_identifier).id
    letter_provider.endpoint_url = endpoint_url
    letter_provider.auth_method = auth_method
    letter_provider.auth_config = auth_config
    letter_provider.address_placement = address_placement
    letter_provider.updated_by_id = updated_by_id
    db.session.add(letter_provider)

    _clear_cached_organisation_and_services(organisation_id)
    return letter_provider


@autocommit
def dao_delete_organisation_letter_provider(organisation_id) -> None:
    OrganisationLetterProvider.query.filter_by(organisation_id=organisation_id).delete()
    _clear_cached_organisation_and_services(organisation_id)


def _clear_cached_organisation_and_services(organisation_id):
    # the letter provider decides the address placement of all the organisation's services' letters
    redis_store.delete(f"organisation-{organisation_id}")
    for (service_id,) in db.session.query(Service.id).filter(Service.organisation_id == organisation_id):
        redis_store.delete(f"service-{service_id}")
