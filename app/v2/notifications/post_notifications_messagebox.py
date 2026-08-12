from datetime import UTC, datetime

import sentry_sdk
from flask import current_app, jsonify, request
from gds_metrics import Histogram

from app import api_user, authenticated_service, db, encryption, notify_celery
from app.config import QueueNames, QueueNamesNL, TaskNamesNL
from app.constants import (
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    MESSAGEBOX_TERMINAL_STATUSES,
    MESSAGEBOX_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PENDING_VIRUS_CHECK,
)
from app.dao import notifications_dao
from app.dao.templates_messagebox_dao import get_messagebox_template
from app.messagebox.utils import upload_messagebox_attachments
from app.notifications.process_notifications import (
    persist_notification,
)
from app.notifications.validators import (
    check_messagebox_attachments_within_size_limit,
    check_rate_limiting,
    check_service_has_oin,
    check_service_has_permission,
)
from app.schema_validation import validate
from app.v2.errors import BadRequestError
from app.v2.notifications import v2_notification_blueprint
from app.v2.notifications.notification_schemas import post_messagebox_request
from app.v2.utils import get_valid_json

POST_NOTIFICATION_JSON_PARSE_DURATION_SECONDS = Histogram(
    "post_notification_messagebox_json_parse_duration_seconds",
    "Time taken to parse and validate post request json",
)


@v2_notification_blueprint.route(f"/{MESSAGEBOX_TYPE}", methods=["POST"])
def post_notification_messagebox():
    check_rate_limiting(authenticated_service, api_user, notification_type=MESSAGEBOX_TYPE)

    check_service_has_permission(authenticated_service, MESSAGEBOX_TYPE)

    with POST_NOTIFICATION_JSON_PARSE_DURATION_SECONDS.time():
        request_json = get_valid_json()
        form = validate(request_json, post_messagebox_request)
        notification = process_messagebox_notification(
            messagebox_data=form,
            api_key=api_user,
            service=authenticated_service,
        )

    return jsonify(notification), 201


def process_messagebox_notification(*, messagebox_data, api_key, service):
    test_key = api_key.key_type == KEY_TYPE_TEST

    if api_key.key_type == KEY_TYPE_TEAM:
        raise BadRequestError(message="Cannot send messagebox messages with a team api key", status_code=403)

    if service.restricted and not test_key:
        raise BadRequestError(message="Cannot send messagebox messages when service is in trial mode", status_code=403)

    check_service_has_oin(service)
    check_messagebox_attachments_within_size_limit(messagebox_data.get("attachments", []))

    status = NOTIFICATION_PENDING_VIRUS_CHECK
    updated_at = None

    if test_key:
        status = NOTIFICATION_DELIVERED
        updated_at = datetime.now(UTC)

    template = get_messagebox_template(service.id)

    try:
        notification = persist_notification(
            template_id=template.id,
            template_version=template.version,
            recipient=encryption.encrypt(messagebox_data.get("recipient")),
            service=service,
            status=status,
            personalisation={
                "message": messagebox_data["message"],
                "subject": messagebox_data.get("subject", "Berichtenboxbericht"),
                "message_type": messagebox_data.get("message_type"),
            },
            notification_type=MESSAGEBOX_TYPE,
            api_key_id=api_key.id,
            key_type=api_key.key_type,
            client_reference=messagebox_data.get("reference", None),
            updated_at=updated_at,
            _autocommit=False,
        )

        sentry_sdk.set_tag("notification_id", str(notification.id))

        if status in MESSAGEBOX_TERMINAL_STATUSES:
            # Test-key sends are created already-delivered (see `status` above)
            # and never pass through _update_notification_status, so the BSN
            # must be wiped here instead -- the retention guarantee is
            # unconditional, not just for real (non-test-key) sends.
            notification.to = None
            notification.normalised_to = None

        upload_messagebox_attachments(notification, messagebox_data.get("attachments", []))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    resp = {"id": notification.id, "uri": f"{request.url_root}v2/notifications/{str(notification.id)}"}

    if template.service.organisation_id:
        resp["organisation_id"] = template.service.organisation_id

    if current_app.config["ANTIVIRUS_ENABLED"]:
        current_app.logger.info("Calling task scan-file for %s", notification.id)
        notify_celery.send_task(
            name=TaskNamesNL.MESSAGEBOX_SCAN_ATTACHMENTS,
            kwargs={"notification_id": notification.id},
            queue=QueueNames.ANTIVIRUS,
        )
    else:
        current_app.logger.info("Antivirus disabled, sending messagebox notification %s directly", notification.id)
        notifications_dao.update_notification_status_by_id(notification.id, NOTIFICATION_CREATED)
        notify_celery.send_task(
            name=TaskNamesNL.MESSAGEBOX_DELIVER,
            kwargs={"notification_id": str(notification.id)},
            queue=QueueNamesNL.MESSAGEBOX,
        )

    return resp
