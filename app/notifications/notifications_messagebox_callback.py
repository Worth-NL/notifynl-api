from flask import Blueprint, jsonify, request

from app.celery.process_messagebox_client_response_tasks import (
    process_messagebox_client_response,
)
from app.config import QueueNames
from app.errors import InvalidRequest, register_errors

messagebox_callback_blueprint = Blueprint("messagebox_callback", __name__, url_prefix="/notifications")
register_errors(messagebox_callback_blueprint)


@messagebox_callback_blueprint.route("/messagebox", methods=["POST"])
def process_messagebox_response():
    client_name = "Messagebox"
    errors = validate_callback_data(data=request.form, fields=["status", "reference"], client_name=client_name)
    if errors:
        raise InvalidRequest(errors, status_code=400)

    status = request.form.get("status")
    detailed_status_code = request.form.get("code")
    provider_reference = request.form.get("reference")

    process_messagebox_client_response.apply_async(
        [status, provider_reference, client_name, detailed_status_code], queue=QueueNames.MESSAGEBOX_CALLBACKS
    )

    return jsonify(result="success"), 200


def validate_callback_data(data, fields, client_name):
    errors = []
    for f in fields:
        if not str(data.get(f, "")):
            error = f"{client_name} callback failed: {f} missing"
            errors.append(error)
    return errors if len(errors) > 0 else None
