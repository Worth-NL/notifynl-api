from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from app.constants import ServiceCallbackTypes
from app.dao.service_callback_api_dao import (
    delete_service_callback_api,
    get_service_callback_api,
    reset_service_callback_api,
    save_service_callback_api,
)
from app.dao.service_inbound_api_dao import (
    delete_service_inbound_api,
    get_service_inbound_api,
    reset_service_inbound_api,
    save_service_inbound_api,
)
from app.errors import InvalidRequest, register_errors
from app.models import ServiceCallbackApi, ServiceInboundApi
from app.schema_validation import validate
from app.service.service_callback_api_schema import (
    create_service_callback_api_schema,
    update_service_callback_api_schema,
)

service_callback_blueprint = Blueprint("service_callback", __name__, url_prefix="/service/<uuid:service_id>")

register_errors(service_callback_blueprint)


@service_callback_blueprint.route("/inbound-api", methods=["POST"])
def create_service_inbound_api(service_id):
    data = request.get_json()
    validate(data, create_service_callback_api_schema)
    data["service_id"] = service_id

    if data.get("callback_type"):
        del data["callback_type"]

    inbound_api = ServiceInboundApi(**data)
    try:
        save_service_inbound_api(inbound_api)
    except SQLAlchemyError as e:
        return handle_sql_error(e, "service_inbound_api")

    return jsonify(data=inbound_api.serialize()), 201


@service_callback_blueprint.route("/inbound-api/<uuid:inbound_api_id>", methods=["POST"])
def update_service_inbound_api(service_id, inbound_api_id):
    data = request.get_json()
    validate(data, update_service_callback_api_schema)

    to_update = get_service_inbound_api(inbound_api_id, service_id)

    reset_service_inbound_api(
        service_inbound_api=to_update,
        updated_by_id=data["updated_by_id"],
        url=data.get("url", None),
        bearer_token=data.get("bearer_token", None),
    )
    return jsonify(data=to_update.serialize()), 200


@service_callback_blueprint.route("/inbound-api/<uuid:inbound_api_id>", methods=["GET"])
def fetch_service_inbound_api(service_id, inbound_api_id):
    inbound_api = get_service_inbound_api(inbound_api_id, service_id)

    return jsonify(data=inbound_api.serialize()), 200


@service_callback_blueprint.route("/inbound-api/<uuid:inbound_api_id>", methods=["DELETE"])
def remove_service_inbound_api(service_id, inbound_api_id):
    inbound_api = get_service_inbound_api(inbound_api_id, service_id)

    if not inbound_api:
        error = "Service inbound API not found"
        raise InvalidRequest(error, status_code=404)

    delete_service_inbound_api(inbound_api)
    return "", 204


# delivery-receipt callback endpoints
@service_callback_blueprint.route("/delivery-receipt-api", methods=["POST"])
def create_delivery_receipt_callback_api(service_id):
    callback_type = ServiceCallbackTypes.delivery_status.value
    return _create_service_callback_api(service_id, callback_type)


@service_callback_blueprint.route("/delivery-receipt-api/<uuid:callback_api_id>", methods=["POST"])
def update_delivery_receipt_callback_api(service_id, callback_api_id):
    callback_type = ServiceCallbackTypes.delivery_status.value
    to_update = _update_service_callback_api(callback_api_id, service_id, callback_type)
    return jsonify(data=to_update.serialize()), 200


@service_callback_blueprint.route("/delivery-receipt-api/<uuid:callback_api_id>", methods=["GET"])
def fetch_delivery_receipt_callback_api(service_id, callback_api_id):
    callback_type = ServiceCallbackTypes.delivery_status.value
    return _fetch_service_callback_api(callback_api_id, service_id, callback_type)


@service_callback_blueprint.route("/delivery-receipt-api/<uuid:callback_api_id>", methods=["DELETE"])
def remove_delivery_receipt_callback_api(service_id, callback_api_id):
    callback_type = ServiceCallbackTypes.delivery_status.value
    _remove_service_callback_api(callback_api_id, service_id, callback_type)
    return "", 204


# returned letter callback endpoints
@service_callback_blueprint.route("/returned-letter-api", methods=["POST"])
def create_returned_letter_callback_api(service_id):
    callback_type = ServiceCallbackTypes.returned_letter.value
    return _create_service_callback_api(service_id, callback_type)


@service_callback_blueprint.route("/returned-letter-api/<uuid:callback_api_id>", methods=["POST"])
def update_returned_letter_callback_api(service_id, callback_api_id):
    callback_type = ServiceCallbackTypes.returned_letter.value
    to_update = _update_service_callback_api(callback_api_id, service_id, callback_type)
    return jsonify(data=to_update.serialize()), 200


@service_callback_blueprint.route("/returned-letter-api/<uuid:callback_api_id>", methods=["GET"])
def fetch_returned_letter_callback_api(service_id, callback_api_id):
    callback_type = ServiceCallbackTypes.returned_letter.value
    return _fetch_service_callback_api(callback_api_id, service_id, callback_type)


@service_callback_blueprint.route("/returned-letter-api/<uuid:callback_api_id>", methods=["DELETE"])
def remove_returned_letter_callback_api(service_id, callback_api_id):
    callback_type = ServiceCallbackTypes.returned_letter.value
    _remove_service_callback_api(callback_api_id, service_id, callback_type)
    return "", 204


# helper callback methods
def _create_service_callback_api(service_id, callback_type):
    data = request.get_json()
    validate(data, create_service_callback_api_schema)
    data["service_id"] = service_id

    # This is a temporary hack that will be removed in a future update once the admin
    # app has been updated to include callback_type during callback API calls.
    if not data.get("callback_type"):
        data["callback_type"] = callback_type

    callback_api = ServiceCallbackApi(**data)
    try:
        save_service_callback_api(callback_api)
    except SQLAlchemyError as e:
        return handle_sql_error(e, "service_callback_api")
    return jsonify(data=callback_api.serialize()), 201


def _update_service_callback_api(callback_api_id, service_id, callback_type):
    data = request.get_json()
    validate(data, update_service_callback_api_schema)
    to_update = get_service_callback_api(callback_api_id, service_id, callback_type)
    reset_service_callback_api(
        service_callback_api=to_update,
        updated_by_id=data["updated_by_id"],
        url=data.get("url", None),
        bearer_token=data.get("bearer_token", None),
    )
    return to_update


def _fetch_service_callback_api(callback_api_id, service_id, callback_type):
    callback_api = get_service_callback_api(callback_api_id, service_id, callback_type)
    return jsonify(data=callback_api.serialize()), 200


def _remove_service_callback_api(callback_api_id, service_id, callback_type):
    callback_api = get_service_callback_api(callback_api_id, service_id, callback_type)
    if not callback_api:
        error = "Service delivery receipt callback API not found"
        raise InvalidRequest(error, status_code=404)
    delete_service_callback_api(callback_api)


def handle_sql_error(e, table_name):
    if (
        hasattr(e, "orig")
        and hasattr(e.orig, "pgerror")
        and e.orig.pgerror
        and (f'duplicate key value violates unique constraint "ix_{table_name}_service_id"' in e.orig.pgerror)
    ):
        return (
            jsonify(result="error", message={"name": ["You can only have one URL and bearer token for your service."]}),
            400,
        )
    elif (
        hasattr(e, "orig")
        and hasattr(e.orig, "pgerror")
        and e.orig.pgerror
        and (
            f'insert or update on table "{table_name}" violates '
            f'foreign key constraint "{table_name}_service_id_fkey"' in e.orig.pgerror
        )
    ):
        return jsonify(result="error", message="No result found"), 404
    else:
        raise e
