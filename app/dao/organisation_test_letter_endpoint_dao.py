from app import db, redis_store
from app.dao.dao_utils import autocommit
from app.models_nl import OrganisationTestLetterEndpoint


def dao_get_organisation_test_letter_endpoint(organisation_id) -> OrganisationTestLetterEndpoint | None:
    return OrganisationTestLetterEndpoint.query.filter_by(organisation_id=organisation_id).one_or_none()


@autocommit
def dao_set_organisation_test_letter_endpoint(
    organisation_id, *, endpoint_url, auth_method, auth_config, updated_by_id
) -> OrganisationTestLetterEndpoint:
    test_endpoint = dao_get_organisation_test_letter_endpoint(organisation_id) or OrganisationTestLetterEndpoint(
        organisation_id=organisation_id
    )
    test_endpoint.endpoint_url = endpoint_url
    test_endpoint.auth_method = auth_method
    test_endpoint.auth_config = auth_config
    test_endpoint.updated_by_id = updated_by_id
    db.session.add(test_endpoint)
    _clear_cached_organisation(organisation_id)
    return test_endpoint


@autocommit
def dao_delete_organisation_test_letter_endpoint(organisation_id) -> None:
    OrganisationTestLetterEndpoint.query.filter_by(organisation_id=organisation_id).delete()
    _clear_cached_organisation(organisation_id)


def _clear_cached_organisation(organisation_id):
    # the organisation's JSON summarises its test endpoint; no service JSON does
    redis_store.delete(f"organisation-{organisation_id}")
