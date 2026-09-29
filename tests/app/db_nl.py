from app import db
from app.dao.provider_details_dao import get_provider_details_by_identifier
from app.letters_nl.constants import LETTER_PROVIDER_PINGEN
from app.models_nl import LetterProviderReference, OrganisationLetterProvider


def create_organisation_letter_provider(
    organisation,
    provider_identifier=LETTER_PROVIDER_PINGEN,
    endpoint_url=None,
    auth_method=None,
    auth_config=None,
    address_placement="60mm",
    updated_by=None,
):
    letter_provider = OrganisationLetterProvider(
        organisation_id=organisation.id,
        provider_details_id=get_provider_details_by_identifier(provider_identifier).id,
        endpoint_url=endpoint_url,
        auth_method=auth_method,
        address_placement=address_placement,
        updated_by_id=updated_by.id if updated_by else None,
    )
    letter_provider.auth_config = auth_config
    db.session.add(letter_provider)
    db.session.commit()
    return letter_provider


def create_letter_provider_reference(notification_id, provider, provider_reference):
    reference = LetterProviderReference(
        notification_id=notification_id, provider=provider, provider_reference=provider_reference
    )
    db.session.add(reference)
    db.session.commit()
    return reference
