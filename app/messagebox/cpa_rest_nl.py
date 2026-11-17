"""Platform-admin endpoints for messagebox CPAs (admin-JWT protected). Guardrails: app/messagebox/cpa_nl.py."""

from ebms_adapter_client import EbmsAdapterError
from flask import Blueprint, abort, current_app, jsonify, request

from app.dao.messagebox_cpa_dao_nl import dao_get_messagebox_cpa_selection, dao_get_messagebox_cpa_selection_history
from app.errors import register_errors
from app.messagebox import cpa_nl
from app.messagebox.constants import CPA_PURPOSES
from app.schema_validation import validate
from app.schema_validation.definitions import uuid

messagebox_cpa_blueprint = Blueprint("messagebox_cpa", __name__)
register_errors(messagebox_cpa_blueprint)

# A Logius CPA is about 25 kB; this only keeps a mistaken upload from reaching ebms-core.
MAX_CPA_LENGTH = 1_000_000

cpa_xml_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "POST messagebox CPA schema",
    "type": "object",
    "properties": {
        "cpa_xml": {"type": "string", "minLength": 1, "maxLength": MAX_CPA_LENGTH},
        "purpose": {"enum": list(CPA_PURPOSES)},
    },
    "required": ["cpa_xml", "purpose"],
    "additionalProperties": False,
}

select_cpa_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "POST messagebox CPA selection schema",
    "type": "object",
    "properties": {
        "cpa_id": {"type": "string", "minLength": 1, "maxLength": 255},
        # a BerichtType registered for this purpose's Logius environment in the Berichtenbox Leveranciersportaal
        "message_type": {"type": "string", "minLength": 1, "maxLength": 255},
        "updated_by_id": uuid,
    },
    "required": ["cpa_id", "message_type", "updated_by_id"],
    "additionalProperties": False,
}


@messagebox_cpa_blueprint.errorhandler(cpa_nl.CpaRejected)
def cpa_rejected(error: cpa_nl.CpaRejected):
    body = {"result": "error", "message": error.message}
    if error.assessment is not None:
        body["assessment"] = error.assessment.serialize()
        body["summary"] = cpa_nl.serialize_summary(error.assessment.summary)
    return jsonify(body), 400


@messagebox_cpa_blueprint.errorhandler(EbmsAdapterError)
def ebms_core_error(error: EbmsAdapterError):
    current_app.logger.warning("ebms-core request for messagebox CPAs failed: %s", error)
    return jsonify(result="error", message=f"ebms-core couldn't handle the request: {error}"), 502


def _check_purpose(purpose: str) -> None:
    if purpose not in CPA_PURPOSES:
        abort(404)


@messagebox_cpa_blueprint.route("/cpas", methods=["GET"])
def get_messagebox_cpas():
    return jsonify(data=[listing.serialize() for listing in cpa_nl.list_cpas()])


@messagebox_cpa_blueprint.route("/cpas/validate", methods=["POST"])
def validate_messagebox_cpa():
    data = request.get_json()
    validate(data, cpa_xml_schema)
    assessment = cpa_nl.validate(data["cpa_xml"], data["purpose"])
    return jsonify(data={"summary": cpa_nl.serialize_summary(assessment.summary), "assessment": assessment.serialize()})


@messagebox_cpa_blueprint.route("/cpas", methods=["POST"])
def upload_messagebox_cpa():
    data = request.get_json()
    validate(data, cpa_xml_schema)
    assessment = cpa_nl.upload(data["cpa_xml"], data["purpose"])
    current_app.logger.info(
        "Messagebox CPA %s uploaded to ebms-core for %s",
        assessment.summary.cpa_id,
        data["purpose"],
        extra={"cpa_id": assessment.summary.cpa_id, "ebms_cpa_purpose": data["purpose"]},
    )
    return jsonify(
        data={"summary": cpa_nl.serialize_summary(assessment.summary), "assessment": assessment.serialize()}
    ), 201


@messagebox_cpa_blueprint.route("/selection/<purpose>", methods=["GET"])
def get_messagebox_cpa_selection(purpose):
    _check_purpose(purpose)
    selection = dao_get_messagebox_cpa_selection(purpose)
    return jsonify(data=selection.serialize() if selection else None)


@messagebox_cpa_blueprint.route("/selection/<purpose>", methods=["POST"])
def select_messagebox_cpa(purpose):
    _check_purpose(purpose)
    data = request.get_json()
    validate(data, select_cpa_schema)
    selection = cpa_nl.select(purpose, data["cpa_id"], message_type=data["message_type"], user_id=data["updated_by_id"])
    current_app.logger.info(
        "Messagebox CPA %s selected for %s",
        selection.cpa_id,
        purpose,
        extra={"cpa_id": selection.cpa_id, "ebms_cpa_purpose": purpose, "user_id": data["updated_by_id"]},
    )
    return jsonify(data=selection.serialize())


@messagebox_cpa_blueprint.route("/selection/<purpose>/history", methods=["GET"])
def get_messagebox_cpa_selection_history(purpose):
    _check_purpose(purpose)
    return jsonify(data=[entry.serialize() for entry in dao_get_messagebox_cpa_selection_history(purpose)])
