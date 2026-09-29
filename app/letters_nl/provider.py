from flask import current_app

from app.dao.organisation_letter_provider_dao import dao_get_organisation_letter_provider
from app.letters_nl.constants import LETTER_PROVIDER_PINGEN


def resolve_letter_provider(organisation_id):
    """
    The client and configuration to send an organisation's letters with: its own letter provider if that's completely
    configured, otherwise Pingen (the default). Returns (client, OrganisationLetterProvider or None).
    """
    from app import notification_provider_clients

    letter_provider = dao_get_organisation_letter_provider(organisation_id)
    if letter_provider and letter_provider.is_complete():
        return notification_provider_clients.get_letter_client(letter_provider.provider.identifier), letter_provider

    if letter_provider:
        current_app.logger.warning(
            "Letter provider %s of organisation %s is not completely configured, sending with %s instead",
            letter_provider.provider.identifier,
            organisation_id,
            LETTER_PROVIDER_PINGEN,
            extra={"organisation_id": organisation_id, "provider_name": letter_provider.provider.identifier},
        )
    return notification_provider_clients.get_letter_client(LETTER_PROVIDER_PINGEN), None
