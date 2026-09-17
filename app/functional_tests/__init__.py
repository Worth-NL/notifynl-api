import datetime
import uuid

from flask import Blueprint, jsonify, request

from app import db
from app.dao.organisation_dao import (
    dao_add_user_to_organisation,
    dao_get_organisation_by_id,
    dao_remove_user_from_organisation,
)
from app.dao.permissions_dao import permission_dao
from app.dao.services_dao import (
    dao_add_user_to_service,
    dao_fetch_all_services_created_by_user,
    delete_service_and_all_associated_db_objects,
)
from app.dao.users_dao import delete_user_and_all_associated_db_objects, delete_user_verify_codes
from app.errors import InvalidRequest, register_errors
from app.functional_tests.fixtures import (
    create_fixture,
    delete_fixture,
    delete_fixture_by_run_id,
    stale_fixture_service_ids,
)
from app.functional_tests.testing_schemas import (
    create_fixture_schema,
    create_functional_test_users_schema,
)
from app.models import Permission, Service, User
from app.schema_validation import validate

test_blueprint = Blueprint("functional_tests", __name__, url_prefix="/__testing/functional")
register_errors(test_blueprint)


@test_blueprint.route("/fixtures", methods=["POST"])
def create_functional_test_fixture():
    """
    Creates one ephemeral org + service + admin user + API keys + templates
    for a single CI run, identified by `runId` (e.g. `<github.run_id>-<attempt>`).
    See app/functional_tests/fixtures.py for the full shape and why this is
    kept separate from the long-lived functional/performance-test fixtures
    in app/functional_tests_fixtures.
    """
    body = request.get_json() or {}
    validate(body, create_fixture_schema)

    fixture = create_fixture(body["runId"])
    return jsonify(fixture), 201


@test_blueprint.route("/fixtures/<string:service_id>", methods=["DELETE"])
def delete_functional_test_fixture(service_id):
    delete_fixture(service_id)
    return "", 204


@test_blueprint.route("/fixtures/by-run/<string:run_id>", methods=["DELETE"])
def delete_functional_test_fixture_by_run_id(run_id):
    """
    Same as delete_functional_test_fixture, but for callers that only know
    `runId` -- notably the Argo Workflow's cleanup (onExit) container, which
    runs in a separate pod from create-fixture and can't read the
    /data/fixture.json it wrote (see fixtures.py's
    delete_fixture_by_run_id docstring).
    """
    delete_fixture_by_run_id(run_id)
    return "", 204


@test_blueprint.route("/fixtures", methods=["GET"])
def list_stale_functional_test_fixtures():
    older_than_minutes_raw = request.args.get("olderThanMinutes")
    if older_than_minutes_raw is None:
        raise InvalidRequest("olderThanMinutes query parameter is required", 400)

    try:
        older_than_minutes = int(older_than_minutes_raw)
    except ValueError:
        raise InvalidRequest("olderThanMinutes must be an integer", 400) from None

    if older_than_minutes < 0:
        raise InvalidRequest("olderThanMinutes must be non-negative", 400)

    return jsonify({"serviceIds": stale_fixture_service_ids(older_than_minutes)}), 200


@test_blueprint.route("/users", methods=["PUT"])
def create_functional_test_users():
    users_info = request.get_json()
    validate(users_info, create_functional_test_users_schema)

    for user_info in users_info:
        created = False
        if not (user := User.query.filter_by(email_address=user_info["email_address"]).one_or_none()):
            created = True
            user = User()
            user.id = uuid.uuid4()
            user.created_at = datetime.datetime.utcnow()
            db.session.add(user)

        user.name = user_info["name"]
        user.email_address = user_info["email_address"]
        user.mobile_number = user_info["mobile_number"]
        user.auth_type = user_info["auth_type"]
        user.password = user_info["password"]
        user.state = user_info["state"]
        user.email_access_validated_at = datetime.datetime.utcnow()
        user.platform_admin = False

        permissions = [
            Permission(service_id=user_info["service_id"], user_id=user.id, permission=p)
            for p in user_info["permissions"]
        ]

        service = Service.query.filter_by(id=user_info["service_id"]).one()
        if created:
            dao_add_user_to_service(service, user, permissions)
        else:
            permission_dao.set_user_service_permission(user, service, permissions, replace=True)

        # Remove user from any organisations it's in, so that we can cleanly set it up according to the current
        # request
        for organisation in user.organisations:
            dao_remove_user_from_organisation(organisation=organisation, user=user)

        organisation_id = user_info.get("organisation_id")
        if organisation_id:
            dao_get_organisation_by_id(organisation_id)
            dao_add_user_to_organisation(organisation_id, str(user.id), [])

        db.session.commit()

    return "ok", 201


@test_blueprint.route("/users/<string:email_address>", methods=["DELETE"])
def delete_functional_test_user(email_address):
    """
    Deletes a user created for testing (e.g. via a smoke-test's self-registration
    flow), along with any service *they created themselves*, so a test suite
    driving this blueprint (local dev, or a future PR-preview environment with
    REGISTER_FUNCTIONAL_TESTING_BLUEPRINT on) can clean up after itself without
    shell access.

    Deliberately narrower than app/commands.py's purge_functional_test_data: this
    only deletes services the user *created* (dao_fetch_all_services_created_by_user),
    never every service they merely belong to. A user can join an existing,
    persistent, shared service (e.g. accepting a team-member invite) without having
    created it -- deleting that would take the shared service down with them.
    delete_user_and_all_associated_db_objects already safely removes the user's
    *membership* from any such service without touching the service itself.
    Confirmed live: an earlier version of this endpoint using
    dao_fetch_all_services_by_user attempted to delete this meta-repo's own shared
    smoke-test service for an invited-and-accepted user, and only a foreign-key
    violation (a template history row) stopped it from completing.
    """
    user = User.query.filter_by(email_address=email_address).one_or_none()
    if not user:
        return "", 204

    for service in dao_fetch_all_services_created_by_user(user.id):
        delete_service_and_all_associated_db_objects(service)

    delete_user_verify_codes(user)
    delete_user_and_all_associated_db_objects(user)

    return "", 204
