from cryptography.fernet import InvalidToken
from flask import Blueprint, jsonify, request

from app.dao.organisation_dao import dao_get_organisation_by_id
from app.dao.organisation_letter_provider_dao import (
    dao_delete_organisation_letter_provider,
    dao_get_organisation_letter_provider,
    dao_set_organisation_letter_provider,
)
from app.errors import InvalidRequest, register_errors
from app.letters_nl.constants import (
    ADDRESS_PLACEMENTS,
    AUTH_METHOD_API_KEY,
    AUTH_METHOD_OAUTH,
    AUTH_METHODS,
    DEFAULT_API_KEY_HEADER,
    LETTER_PROVIDER_PINGEN,
    LETTER_PROVIDER_REST_ENDPOINT,
    LETTER_PROVIDERS,
    OPTIONAL_AUTH_CONFIG_FIELDS,
    PINGEN_ADDRESS_PLACEMENT,
    REQUIRED_AUTH_CONFIG_FIELDS,
    SECRET_AUTH_CONFIG_FIELDS,
)
from app.letters_nl.url_validation import InvalidLetterEndpointUrl, validate_letter_endpoint_url
from app.schema_validation import validate
from app.schema_validation.definitions import uuid

organisation_letter_provider_blueprint = Blueprint("organisation_letter_provider", __name__)
register_errors(organisation_letter_provider_blueprint)

ALL_AUTH_CONFIG_FIELDS = sorted(
    {field for fields in REQUIRED_AUTH_CONFIG_FIELDS.values() for field in fields}
    | {field for fields in OPTIONAL_AUTH_CONFIG_FIELDS.values() for field in fields}
)

post_set_organisation_letter_provider_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "description": "POST organisation letter provider schema",
    "type": "object",
    "properties": {
        "provider": {"enum": LETTER_PROVIDERS},
        "endpoint_url": {"type": "string", "minLength": 1},
        "auth_method": {"enum": AUTH_METHODS},
        # secrets are write-only: leave one out (or empty) to keep the stored value
        "auth_config": {
            "type": "object",
            "properties": {field: {"type": ["string", "null"]} for field in ALL_AUTH_CONFIG_FIELDS},
            "additionalProperties": False,
        },
        "address_placement": {"enum": ADDRESS_PLACEMENTS},
        "updated_by_id": uuid,
    },
    "required": ["provider", "updated_by_id"],
    "if": {"properties": {"provider": {"const": LETTER_PROVIDER_REST_ENDPOINT}}},
    "then": {"required": ["endpoint_url", "auth_method", "address_placement"]},
    "additionalProperties": False,
}


@organisation_letter_provider_blueprint.route("/organisations/<uuid:organisation_id>/letter-provider", methods=["GET"])
def get_organisation_letter_provider(organisation_id):
    dao_get_organisation_by_id(organisation_id)
    letter_provider = dao_get_organisation_letter_provider(organisation_id)
    return jsonify(data=letter_provider.serialize() if letter_provider else None)


@organisation_letter_provider_blueprint.route("/organisations/<uuid:organisation_id>/letter-provider", methods=["POST"])
def set_organisation_letter_provider(organisation_id):
    data = request.get_json()
    validate(data, post_set_organisation_letter_provider_schema)
    dao_get_organisation_by_id(organisation_id)

    if data["provider"] == LETTER_PROVIDER_PINGEN:
        endpoint_url, auth_method, auth_config = None, None, None
        address_placement = PINGEN_ADDRESS_PLACEMENT
    else:
        endpoint_url = data["endpoint_url"]
        auth_method = data["auth_method"]
        address_placement = data["address_placement"]
        auth_config = _merge_auth_config(
            dao_get_organisation_letter_provider(organisation_id), auth_method, data.get("auth_config", {})
        )
        _validate_rest_endpoint(endpoint_url, auth_method, auth_config)

    letter_provider = dao_set_organisation_letter_provider(
        organisation_id,
        provider_identifier=data["provider"],
        endpoint_url=endpoint_url,
        auth_method=auth_method,
        auth_config=auth_config,
        address_placement=address_placement,
        updated_by_id=data["updated_by_id"],
    )
    return jsonify(data=letter_provider.serialize())


@organisation_letter_provider_blueprint.route(
    "/organisations/<uuid:organisation_id>/letter-provider", methods=["DELETE"]
)
def delete_organisation_letter_provider(organisation_id):
    dao_get_organisation_by_id(organisation_id)
    dao_delete_organisation_letter_provider(organisation_id)
    return "", 204


def _merge_auth_config(existing, auth_method, update) -> dict:
    """Secrets left out (or empty) keep their stored value, as long as the auth method didn't change."""
    stored = {}
    same_auth_method = existing and existing.auth_method == auth_method
    if same_auth_method and existing.provider.identifier == LETTER_PROVIDER_REST_ENDPOINT:
        try:
            stored = existing.auth_config or {}
        except (InvalidToken, ValueError):
            stored = {}

    auth_config = {}
    for field in REQUIRED_AUTH_CONFIG_FIELDS[auth_method] + OPTIONAL_AUTH_CONFIG_FIELDS[auth_method]:
        if field in SECRET_AUTH_CONFIG_FIELDS:
            value = update.get(field) or stored.get(field)
        else:
            value = update[field] if field in update else stored.get(field)
        if value:
            auth_config[field] = value

    if auth_method == AUTH_METHOD_API_KEY:
        auth_config.setdefault("api_key_header", DEFAULT_API_KEY_HEADER)
    return auth_config


def _validate_rest_endpoint(endpoint_url, auth_method, auth_config):
    missing = [field for field in REQUIRED_AUTH_CONFIG_FIELDS[auth_method] if not auth_config.get(field)]
    if missing:
        raise InvalidRequest(f"Missing {', '.join(missing)} for auth method {auth_method}", status_code=400)

    urls = [endpoint_url] + ([auth_config["token_endpoint"]] if auth_method == AUTH_METHOD_OAUTH else [])
    for url in urls:
        try:
            validate_letter_endpoint_url(url)
        except InvalidLetterEndpointUrl as e:
            raise InvalidRequest(str(e), status_code=400) from e
