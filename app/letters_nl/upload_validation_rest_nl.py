"""
[NotifyNL] Checks a letter a team member uploads in notifynl-admin ("Upload een brief"). Admin used to call
template-preview itself; going through the API means the API alone decides which address window
(Service.letter_address_window) a service's precompiled letters are checked against, wherever they come from.
"""

import base64
import binascii
import json

from flask import Blueprint, current_app, jsonify, request
from flask.ctx import has_request_context
from requests import post as requests_post

from app.dao.services_dao import dao_fetch_service_by_id
from app.errors import InvalidRequest, register_errors
from app.schema_validation import validate

letter_upload_blueprint = Blueprint("letter_upload", __name__, url_prefix="/service/<uuid:service_id>/letter-upload")
register_errors(letter_upload_blueprint)

sanitise_letter_upload_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "POST sanitise an uploaded letter",
    "type": "object",
    "properties": {
        "file": {"type": "string", "minLength": 1},
        "upload_id": {"type": "string", "minLength": 1},
        "allow_international_letters": {"type": "boolean"},
    },
    "required": ["file", "upload_id"],
    "additionalProperties": False,
}

overlay_letter_upload_page_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "POST overlay of one page of an uploaded letter",
    "type": "object",
    "properties": {
        "file": {"type": "string", "minLength": 1},
        "page_number": {"type": "integer", "minimum": 1},
    },
    "required": ["file", "page_number"],
    "additionalProperties": False,
}


@letter_upload_blueprint.route("/sanitise", methods=["POST"])
def sanitise_letter_upload(service_id):
    """template-preview's answer as is: its status (400 for a letter that failed validation) and its JSON."""
    data = request.get_json()
    validate(data, sanitise_letter_upload_schema)
    service = dao_fetch_service_by_id(service_id)

    response = _post_to_template_preview(
        "/precompiled/sanitise",
        {
            "upload_id": data["upload_id"],
            "allow_international_letters": "true" if data.get("allow_international_letters") else "false",
            **_address_window_params(service),
        },
        _decode_pdf(data["file"]),
    )
    if response.status_code not in (200, 400):
        raise InvalidRequest(
            f"template-preview could not sanitise upload {data['upload_id']}: {response.status_code}", status_code=500
        )

    return jsonify(status_code=response.status_code, data=response.json()), 200


@letter_upload_blueprint.route("/overlay.png", methods=["POST"])
def overlay_letter_upload_page(service_id):
    """One page of an uploaded letter, with the areas it mustn't print in coloured red."""
    data = request.get_json()
    validate(data, overlay_letter_upload_page_schema)
    service = dao_fetch_service_by_id(service_id)

    response = _post_to_template_preview(
        "/precompiled/overlay.png",
        {"page_number": data["page_number"], **_address_window_params(service)},
        _decode_pdf(data["file"]),
    )
    if response.status_code != 200:
        raise InvalidRequest(f"template-preview could not draw the overlay: {response.status_code}", status_code=500)

    return jsonify(png=base64.b64encode(response.content).decode("utf-8")), 200


def _address_window_params(service):
    return {
        "letter_address_placement": service.effective_letter_address_placement,
        "letter_address_window": json.dumps(service.letter_address_window.to_dict(), separators=(",", ":")),
    }


def _decode_pdf(encoded):
    try:
        return base64.b64decode(encoded, validate=True)
    except binascii.Error as e:
        raise InvalidRequest({"file": ["file must be base64 encoded"]}, status_code=400) from e


def _post_to_template_preview(path, params, pdf):
    headers = {"Authorization": f"Token {current_app.config['TEMPLATE_PREVIEW_API_KEY']}"}
    if has_request_context() and hasattr(request, "get_onwards_request_headers"):
        headers.update(request.get_onwards_request_headers())
    return requests_post(
        f"{current_app.config['TEMPLATE_PREVIEW_API_HOST']}{path}", params=params, data=pdf, headers=headers
    )
