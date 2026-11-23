from flask import current_app

from app.dao.organisation_letter_provider_dao import dao_get_organisation_letter_provider
from app.letters_nl.constants import LETTER_PROVIDER_PINGEN, LETTER_PROVIDER_REST_ENDPOINT
from app.letters_nl.test_endpoint import get_test_letter_endpoint
from app.models_nl import complete_letter_provider


class MissingTestLetterEndpoint(Exception):
    """A letter for the organisation's test endpoint, but the organisation has none (any more)."""


def resolve_letter_provider(organisation_id, *, test_key):
    """
    The client and configuration to send an organisation's letters with: its own letter provider if that's completely
    configured, otherwise Pingen (the default). Returns (client, OrganisationLetterProvider or None).

    A letter with a test key goes to the organisation's test endpoint instead, and fails closed: without one it raises
    MissingTestLetterEndpoint and never falls back to Pingen or the live provider. A live letter never looks at it.
    """
    from app import notification_provider_clients

    if test_key:
        test_endpoint = get_test_letter_endpoint(organisation_id)
        if test_endpoint is None:
            raise MissingTestLetterEndpoint(organisation_id)
        return notification_provider_clients.get_letter_client(LETTER_PROVIDER_REST_ENDPOINT), test_endpoint

    letter_provider = dao_get_organisation_letter_provider(organisation_id)
    if complete_letter_provider(letter_provider):
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
