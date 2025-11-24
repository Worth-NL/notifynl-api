import uuid as uuid_type
from datetime import datetime

from flask import jsonify
from gds_metrics import Histogram

from app import (
    api_user,
    authenticated_service,
)
from app.constants import (
    KEY_TYPE_TEST,
    MESSAGEBOX_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
)
from app.dao.templates_messagebox_dao import get_messagebox_template
from app.notifications.process_notifications import (
    persist_notification,
)
from app.schema_validation import validate
from app.v2.notifications import v2_notification_blueprint
from app.v2.utils import get_valid_json

post_messagebox_request = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "POST berichtenbox notification schema",
    "type": "object",
    "title": "POST v2/notifications/berichtenbox",
    "properties": {
        "reference": {"type": "string", "maxLength": 1_000},
    },
    "required": [],
    "additionalProperties": False,
}

POST_NOTIFICATION_JSON_PARSE_DURATION_SECONDS = Histogram(
    "post_notification_messagebox_json_parse_duration_seconds",
    "Time taken to parse and validate post request json",
)


@v2_notification_blueprint.route(f"/{MESSAGEBOX_TYPE}", methods=["POST"])
def post_notification_messagebox():
    # TODO: add rate limiting setting for message box calls
    # check_rate_limiting(authenticated_service, api_user, notification_type=MESSAGEBOX_TYPE)
    with POST_NOTIFICATION_JSON_PARSE_DURATION_SECONDS.time():
        request_json = get_valid_json()
        form = validate(request_json, post_messagebox_request)
        notification = process_messagebox_notification(
            messagebox_data=form,
            api_key=api_user,
            service=authenticated_service,
        )

    # TODO: add check if permission
    # check_service_has_permission(authenticated_service, notification_type=MESSAGEBOX_TYPE)
    # template, template_with_content = validate_template(
    #         form["template_id"],
    #         form.get("personalisation", {}),
    #         authenticated_service,
    #         notification_type,
    #         check_char_count=False,
    #     )

    # TODO: Check add validate
    # form = validate(request_json, post_messagebox_request)

    return jsonify(notification), 201


def process_messagebox_notification(*, messagebox_data, api_key, service, precompiled=False):
    # TODO enable these filters when dev is done
    # if api_key.key_type == KEY_TYPE_TEAM:
    #    raise BadRequestError(message="Cannot send messagebox messages with a team api key", status_code=403)

    # if service.restricted and api_key.key_type != KEY_TYPE_TEST:
    #     raise BadRequestError(message="Cannot send letters when service is in trial mode", status_code=403)

    test_key = api_key.key_type == KEY_TYPE_TEST
    status = NOTIFICATION_CREATED
    updated_at = None

    if test_key:
        status = NOTIFICATION_DELIVERED
        updated_at = datetime.utcnow()

    notification_id = uuid_type.uuid4()

    # TODO: Add messagebox messages as a separate permission admin can enable for an organisation
    # check_service_has_permission(authenticated_service, MESSAGEBOX_TYPE)

    template = get_messagebox_template(authenticated_service.id)

    persist_notification(
        notification_id=notification_id,
        template_id=template.id,
        template_version=template.version,
        recipient="",
        service=service,
        status=status,
        personalisation=None,
        notification_type=MESSAGEBOX_TYPE,
        api_key_id=api_user.id,
        key_type=api_user.key_type,
        client_reference=messagebox_data.get("reference", None),
        updated_at=updated_at,
    )

    resp = create_response_for_post_notification(
        notification_id=notification_id,
        organisation_id=template.service.organisation_id,
    )
    return resp


def create_response_for_post_notification(
    notification_id,
    organisation_id,
):
    return {"notification_id": notification_id, "organisation_id": organisation_id}
