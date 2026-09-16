"""
Ephemeral smoke-test fixtures: one org + service + admin user + API keys +
templates per CI run, created and deleted around a single Argo Workflow
execution (see notifynl-smoke-tests). Distinct from
app/functional_tests_fixtures, which builds the long-lived, shared
functional/performance-test environment -- these fixtures are meant to be
thrown away within minutes, one per PR run, and are identified solely by a
reserved email pattern rather than a tracking table.
"""

import uuid
from datetime import datetime, timedelta

from flask import current_app

from app.constants import EMAIL_AUTH
from app.dao.annual_billing_dao import set_default_free_allowance_for_service
from app.dao.api_key_dao import save_model_api_key
from app.dao.organisation_dao import (
    dao_create_organisation,
    dao_get_organisations_by_partial_name,
)
from app.dao.services_dao import (
    DEFAULT_SERVICE_PERMISSIONS,
    dao_create_service,
    dao_fetch_service_by_id,
    delete_service_and_all_associated_db_objects,
)
from app.dao.templates_dao import dao_create_template
from app.dao.users_dao import (
    delete_user_and_all_associated_db_objects,
    delete_user_verify_codes,
    save_model_user,
)
from app.errors import InvalidRequest
from app.models import Organisation, Service, User
from app.schemas import api_key_schema, template_schema

FIXTURE_EMAIL_DOMAIN = "smoke-test.notifynl.invalid"
FIXTURE_ORG_NAME = "Smoke Tests"
_RUN_ID_MAX_LENGTH = 60
_RESOURCE_ID_MAX_LENGTH = 40


def resource_id_for_run(run_id: str) -> str:
    if not run_id or len(run_id) > _RUN_ID_MAX_LENGTH:
        raise InvalidRequest(f"runId must be non-empty and at most {_RUN_ID_MAX_LENGTH} characters", 400)

    resource_id = "".join(c if c.isalnum() else "-" for c in run_id.lower()).strip("-")
    if not resource_id:
        raise InvalidRequest("runId must contain at least one alphanumeric character", 400)

    return resource_id[:_RESOURCE_ID_MAX_LENGTH]


def fixture_email_for_resource(resource_id: str) -> str:
    return f"smoke-test-{resource_id}@{FIXTURE_EMAIL_DOMAIN}"


def is_fixture_email(email_address: str) -> bool:
    return (
        bool(email_address)
        and email_address.endswith(f"@{FIXTURE_EMAIL_DOMAIN}")
        and email_address.startswith("smoke-test-")
    )


def create_fixture(run_id: str) -> dict:
    """
    Creates one org (shared, idempotent) + one fresh service + one admin
    user + two API keys + two templates, all named/emailed from `run_id`.

    Not wrapped in a single hard DB transaction: each DAO call below commits
    independently, matching this codebase's existing convention (see
    app/functional_tests_fixtures/__init__.py's apply_fixtures, which does
    the same for the long-lived fixture environment). If any step fails
    partway through, we best-effort clean up whatever was already created
    for this resource_id before re-raising, since resource_id (and therefore
    the fixture email) is deterministic and known before any creation
    happens -- unlike the objects' random UUIDs.
    """
    resource_id = resource_id_for_run(run_id)
    email_address = fixture_email_for_resource(resource_id)

    try:
        org = _get_or_create_org()

        admin_user = User()
        admin_user.id = uuid.uuid4()
        admin_user.name = f"Smoke Test {resource_id}"
        admin_user.email_address = email_address
        admin_user.mobile_number = "07700900001"
        admin_user.auth_type = "email_auth"
        admin_user.state = "active"
        admin_user.email_access_validated_at = datetime.utcnow()
        admin_user.created_at = datetime.utcnow()
        admin_password = str(uuid.uuid4())
        save_model_user(admin_user, password=admin_password, validated_email_access=True)

        service = Service.from_json(
            {
                "name": f"Smoke Test {resource_id}",
                "restricted": False,
                "organisation_id": org.id,
                "organisation_type": "central",
                "created_by": admin_user.id,
                "contact_link": current_app.config.get("ADMIN_BASE_URL"),
            }
        )
        # dao_create_service already grants admin_user (the creator) the full
        # default_service_permissions set (permissions_dao.py) -- manage_users,
        # manage_templates, manage_settings, send_texts, send_emails,
        # send_letters, manage_api_keys, view_activity. An earlier version of
        # this function then narrowed that down to just
        # (send_emails, send_texts, view_activity) via an explicit
        # set_user_service_permission(..., replace=True) call, copied from
        # app/functional_tests_fixtures/__init__.py's _grant_permissions --
        # but that helper exists there to grant a *second*, non-creator user
        # permissions, not to re-grant the creator's own. Confirmed live: the
        # narrowed version 403'd every admin-UI flow needing manage_templates/
        # manage_api_keys/manage_users (template CRUD, API key create/revoke,
        # invite team member) with "U hebt geen toestemming om deze pagina te
        # bekijken". Removed entirely -- the creator's default permissions are
        # already exactly what a smoke-test admin needs.
        # EMAIL_AUTH added on top of the defaults: it's a *service*-level
        # permission (SERVICE_PERMISSION_TYPES), separate from admin_user's
        # own auth_type="email_auth" set above -- without it,
        # invite-team-member's "E-maillink" login option isn't even rendered
        # (manage-users/permissions.html gates it on
        # current_service.has_permission('email_auth')). Confirmed live: the
        # invite flow timed out waiting for that radio before this was added.
        dao_create_service(service, admin_user, service_permissions=[*DEFAULT_SERVICE_PERMISSIONS, EMAIL_AUTH])
        set_default_free_allowance_for_service(service=service, year_start=None)

        api_key_normal = _create_api_key("smoke-test-normal", service.id, admin_user.id, "normal")
        api_key_test = _create_api_key("smoke-test-test", service.id, admin_user.id, "test")

        email_template = _create_email_template(service, admin_user.id, resource_id)
        sms_template = _create_sms_template(service, admin_user.id, resource_id)
    except Exception:
        current_app.logger.exception("Failed to create smoke-test fixture for resourceId %s; cleaning up", resource_id)
        _delete_by_email(email_address)
        raise

    return {
        "runId": run_id,
        "resourceId": resource_id,
        "serviceId": str(service.id),
        "organisationId": str(org.id),
        "adminUser": {"id": str(admin_user.id), "emailAddress": email_address, "password": admin_password},
        "apiKeyNormal": f"smoke-test-normal-{service.id}-{api_key_normal.secret}",
        "apiKeyTest": f"smoke-test-test-{service.id}-{api_key_test.secret}",
        "emailTemplateId": str(email_template.id),
        "smsTemplateId": str(sms_template.id),
    }


def delete_fixture(service_id: str) -> bool:
    """Idempotent: returns False (not True) if the service is already gone."""
    try:
        service_uuid = uuid.UUID(str(service_id))
    except ValueError:
        return False

    service = Service.query.filter_by(id=service_uuid).one_or_none()
    if service is None:
        return False

    fixture_admin_users = [user for user in service.users if is_fixture_email(user.email_address)]

    delete_service_and_all_associated_db_objects(service)

    for user in fixture_admin_users:
        delete_user_verify_codes(user)
        delete_user_and_all_associated_db_objects(user)

    return True


def stale_fixture_service_ids(older_than_minutes: int) -> list[str]:
    cutoff = datetime.utcnow() - timedelta(minutes=older_than_minutes)
    stale_fixture_users = User.query.filter(
        User.email_address.like(f"smoke-test-%@{FIXTURE_EMAIL_DOMAIN}"),
        User.created_at < cutoff,
    ).all()

    service_ids: set[str] = set()
    for user in stale_fixture_users:
        for service in user.services:
            service_ids.add(str(service.id))

    return sorted(service_ids)


def _delete_by_email(email_address: str) -> None:
    user = User.query.filter_by(email_address=email_address).one_or_none()
    if user is None:
        return

    for service in list(user.services):
        delete_service_and_all_associated_db_objects(service)

    delete_user_verify_codes(user)
    delete_user_and_all_associated_db_objects(user)


def _get_or_create_org() -> Organisation:
    for org in dao_get_organisations_by_partial_name(FIXTURE_ORG_NAME):
        if org.name == FIXTURE_ORG_NAME:
            return org

    org = Organisation(name=FIXTURE_ORG_NAME, active=True, crown=False, organisation_type="central")
    dao_create_organisation(org)
    return org


def _create_api_key(name, service_id, user_id, key_type):
    request = {"created_by": user_id, "key_type": key_type, "name": name}
    fetched_service = dao_fetch_service_by_id(service_id=service_id)
    valid_api_key = api_key_schema.load(request)
    valid_api_key.service = fetched_service
    save_model_api_key(valid_api_key)
    return valid_api_key


def _create_email_template(service, user_id, resource_id):
    # Content deliberately just ((nonce)) -- notifynl-smoke-tests'
    # send-notification.spec.ts (a fixed, pre-existing test) only ever sends
    # {nonce} as personalisation. An earlier version of this function used
    # ((resourceId)) instead, which that test never supplies -- confirmed
    # live: every real send 400'd with "Missing personalisation: resourceId".
    new_template = template_schema.load(
        {
            "name": f"Smoke Test Email {resource_id}",
            "template_type": "email",
            "content": "Smoke test email. ((nonce))",
            "subject": "Smoke test",
            "created_by": user_id,
            "service": service.id,
        }
    )
    dao_create_template(new_template)
    return new_template


def _create_sms_template(service, user_id, resource_id):
    new_template = template_schema.load(
        {
            "name": f"Smoke Test SMS {resource_id}",
            "template_type": "sms",
            "content": "Smoke test sms. ((nonce))",
            "created_by": user_id,
            "service": service.id,
        }
    )
    dao_create_template(new_template)
    return new_template
