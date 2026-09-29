import hmac
import json
from hashlib import sha256

from flask import Blueprint, current_app, jsonify, request
from itsdangerous import BadSignature

from app import signing
from app.celery.letter_provider_tasks import process_letter_provider_status
from app.config import QueueNames
from app.constants import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_RETURNED_LETTER,
    NOTIFICATION_TECHNICAL_FAILURE,
)
from app.dao.letter_provider_reference_dao import dao_get_notification_id_by_provider_reference
from app.errors import InvalidRequest, register_errors
from app.letters_nl.constants import (
    LETTER_PROVIDER_CALLBACK_PATH,
    LETTER_PROVIDER_PINGEN,
    LETTER_PROVIDER_REST_ENDPOINT,
)
from app.schema_validation import validate

letter_provider_callback_blueprint = Blueprint("letter_provider_callback", __name__)
register_errors(letter_provider_callback_blueprint)

letter_provider_status_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "Status update for a letter from a REST endpoint print provider",
    "type": "object",
    "properties": {
        "status": {
            "enum": [
                NOTIFICATION_DELIVERED,
                NOTIFICATION_PERMANENT_FAILURE,
                NOTIFICATION_TECHNICAL_FAILURE,
                NOTIFICATION_RETURNED_LETTER,
            ]
        },
        "reason": {"type": ["string", "null"], "maxLength": 1000},
        "occurred_at": {"type": ["string", "null"], "format": "date-time"},
    },
    "required": ["status"],
}

# Pingen webhook payload types (https://api.pingen.com/documentation, misc.webhooks)
PINGEN_WEBHOOK_STATUSES = {
    # handed over to the postal service: what DVLA's DESPATCHED used to mean
    "webhook_sent": NOTIFICATION_DELIVERED,
    "webhook_delivered": NOTIFICATION_DELIVERED,
    "webhook_undeliverable": NOTIFICATION_RETURNED_LETTER,
    "webhook_issues": NOTIFICATION_TECHNICAL_FAILURE,
}


@letter_provider_callback_blueprint.route(LETTER_PROVIDER_CALLBACK_PATH, methods=["POST"])
def process_letter_provider_callback():
    """Called by a REST endpoint print provider, on the callbackUrl it got with the letter."""
    try:
        notification_id = signing.decode(request.args.get("token", ""))
    except BadSignature as e:
        raise InvalidRequest("A valid token is required", status_code=403) from e

    data = request.get_json(force=True)
    validate(data, letter_provider_status_schema)

    _queue_status_update(notification_id, LETTER_PROVIDER_REST_ENDPOINT, data["status"], data.get("reason"))
    return {}, 204


@letter_provider_callback_blueprint.route("/notifications/letter/pingen", methods=["POST"])
def process_pingen_webhook():
    payload = request.get_data()
    signing_key = current_app.config.get("PINGEN_WEBHOOK_SIGNING_KEY")
    expected_signature = hmac.new(signing_key.encode(), payload, sha256).hexdigest() if signing_key else None
    if not expected_signature or not hmac.compare_digest(request.headers.get("Signature", ""), expected_signature):
        current_app.logger.warning("Pingen webhook with an invalid signature")
        raise InvalidRequest("Invalid signature", status_code=401)

    try:
        data = json.loads(payload)["data"]
        webhook_type = data["type"]
        deliverable = data["relationships"]["deliverable"]["data"]
    except (ValueError, KeyError, TypeError) as e:
        raise InvalidRequest("Invalid Pingen webhook payload", status_code=400) from e

    # anything we can't act on is acknowledged, otherwise Pingen keeps retrying it
    status = PINGEN_WEBHOOK_STATUSES.get(webhook_type)
    notification_id = dao_get_notification_id_by_provider_reference(LETTER_PROVIDER_PINGEN, deliverable["id"])
    if deliverable.get("type") != "letters" or not status or not notification_id:
        current_app.logger.info(
            "Ignoring Pingen webhook %s for %s %s",
            webhook_type,
            deliverable.get("type"),
            deliverable.get("id"),
            extra={"pingen_webhook_type": webhook_type, "pingen_letter_id": deliverable.get("id")},
        )
        return jsonify(result="ignored"), 200

    _queue_status_update(
        str(notification_id), LETTER_PROVIDER_PINGEN, status, (data.get("attributes") or {}).get("reason")
    )
    return jsonify(result="success"), 200


def _queue_status_update(notification_id, provider, status, reason):
    current_app.logger.info(
        "Letter status %s from %s for notification %s",
        status,
        provider,
        notification_id,
        extra={"notification_id": notification_id, "provider_name": provider, "notification_status": status},
    )
    process_letter_provider_status.apply_async(
        kwargs={"notification_id": notification_id, "provider": provider, "status": status, "reason": reason},
        queue=QueueNames.LETTER_CALLBACKS,
    )
