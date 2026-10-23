import datetime
import json

from cryptography.fernet import InvalidToken
from sqlalchemy.dialects.postgresql import UUID

from app import db, encryption
from app.letters_nl.constants import (
    LETTER_PROVIDER_PINGEN,
    LETTER_PROVIDER_REST_ENDPOINT,
    OPTIONAL_AUTH_CONFIG_FIELDS,
    PINGEN_ADDRESS_PLACEMENT,
    REQUIRED_AUTH_CONFIG_FIELDS,
    SECRET_AUTH_CONFIG_FIELDS,
)
from app.utils import get_dt_string_or_none, get_uuid_string_or_none


class OrganisationLetterProvider(db.Model):
    """
    The print provider an organisation's letters are sent to. Organisations without a (complete) row fall back to
    Pingen, see app/letters_nl/provider.py.
    """

    __tablename__ = "organisation_letter_provider"

    organisation_id = db.Column(UUID(as_uuid=True), db.ForeignKey("organisation.id"), primary_key=True)
    organisation = db.relationship("Organisation", backref=db.backref("letter_provider", uselist=False))
    provider_details_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("provider_details.id"), nullable=False, index=True
    )
    provider = db.relationship("ProviderDetails")
    endpoint_url = db.Column(db.String, nullable=True)
    auth_method = db.Column(db.String, nullable=True)
    address_placement = db.Column(db.String(5), nullable=False, default=PINGEN_ADDRESS_PLACEMENT)
    # Fernet-encrypted JSON, never serialized: see auth_config
    _auth_config = db.Column("auth_config", db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.datetime.utcnow)
    updated_by_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=True)
    updated_by = db.relationship("User")

    @property
    def auth_config(self) -> dict | None:
        if self._auth_config is None:
            return None
        return json.loads(encryption.decrypt(self._auth_config))

    @auth_config.setter
    def auth_config(self, auth_config: dict | None):
        self._auth_config = encryption.encrypt(json.dumps(auth_config)) if auth_config else None

    @property
    def has_credentials(self) -> bool:
        return self._auth_config is not None

    def is_complete(self) -> bool:
        """Whether letters can be sent with this configuration as it stands."""
        if self.provider.identifier == LETTER_PROVIDER_PINGEN:
            return True
        if self.provider.identifier != LETTER_PROVIDER_REST_ENDPOINT:
            return False
        if not self.endpoint_url or self.auth_method not in REQUIRED_AUTH_CONFIG_FIELDS:
            return False
        try:
            auth_config = self.auth_config or {}
        except (InvalidToken, ValueError):
            return False
        return all(auth_config.get(field) for field in REQUIRED_AUTH_CONFIG_FIELDS[self.auth_method])

    def serialize_summary(self) -> dict:
        """Safe to cache with the organisation: no credentials and no decryption."""
        return {
            "identifier": self.provider.identifier,
            "display_name": self.provider.display_name,
            "endpoint_url": self.endpoint_url,
            "auth_method": self.auth_method,
            "address_placement": self.address_placement,
            "has_credentials": self.has_credentials,
        }

    def serialize(self) -> dict:
        """The summary plus the non-secret auth config fields for the current auth method."""
        auth_config_fields = REQUIRED_AUTH_CONFIG_FIELDS.get(self.auth_method, ()) + OPTIONAL_AUTH_CONFIG_FIELDS.get(
            self.auth_method, ()
        )
        try:
            auth_config = self.auth_config or {}
        except (InvalidToken, ValueError):
            auth_config = {}
        return self.serialize_summary() | {
            "organisation_id": str(self.organisation_id),
            "auth_config": {
                field: auth_config.get(field) for field in auth_config_fields if field not in SECRET_AUTH_CONFIG_FIELDS
            },
            "is_complete": self.is_complete(),
            "updated_at": get_dt_string_or_none(self.updated_at),
            "updated_by_id": get_uuid_string_or_none(self.updated_by_id),
        }


class LetterProviderReference(db.Model):
    """
    The id a print provider gave a letter (e.g. Pingen's letter id). No foreign key to notifications: the mapping has
    to survive the move to notification_history, as providers can report back after that.
    """

    __tablename__ = "letter_provider_reference"

    notification_id = db.Column(UUID(as_uuid=True), primary_key=True)
    provider = db.Column(db.String, nullable=False)
    provider_reference = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("provider", "provider_reference", name="uix_letter_provider_reference"),)
