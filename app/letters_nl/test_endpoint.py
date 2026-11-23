from app.constants import KEY_TYPE_TEST
from app.dao.organisation_test_letter_endpoint_dao import dao_get_organisation_test_letter_endpoint
from app.models_nl import OrganisationTestLetterEndpoint


def get_test_letter_endpoint(organisation_id) -> OrganisationTestLetterEndpoint | None:
    """
    The organisation's endpoint for letters sent with a test or team key, if it is completely configured. Without
    one those letters are simulated (research mode).
    """
    if organisation_id is None:
        return None
    test_endpoint = dao_get_organisation_test_letter_endpoint(organisation_id)
    return test_endpoint if test_endpoint and test_endpoint.is_complete() else None


def uses_test_letter_endpoint(notification) -> bool:
    """
    Whether this letter is delivered to its organisation's test endpoint: only letters with a test key (a team key is
    stored as one) and only when the organisation has one. Live letters never are.
    """
    return (
        notification.key_type == KEY_TYPE_TEST
        and get_test_letter_endpoint(notification.service.organisation_id) is not None
    )
