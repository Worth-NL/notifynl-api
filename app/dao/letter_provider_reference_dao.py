from sqlalchemy.dialects.postgresql import insert

from app import db
from app.dao.dao_utils import autocommit
from app.models_nl import LetterProviderPin, LetterProviderReference


def dao_get_letter_provider_reference(notification_id) -> LetterProviderReference | None:
    return LetterProviderReference.query.filter_by(notification_id=notification_id).one_or_none()


def dao_get_notification_id_by_provider_reference(provider, provider_reference):
    reference = LetterProviderReference.query.filter_by(
        provider=provider, provider_reference=provider_reference
    ).one_or_none()
    return reference.notification_id if reference else None


@autocommit
def dao_create_letter_provider_reference(notification_id, provider, provider_reference):
    # a retried delivery can report the same letter again
    db.session.execute(
        insert(LetterProviderReference)
        .values(notification_id=notification_id, provider=provider, provider_reference=provider_reference)
        .on_conflict_do_nothing()
    )


def dao_get_letter_provider_pin(notification_id) -> LetterProviderPin | None:
    return LetterProviderPin.query.filter_by(notification_id=notification_id).one_or_none()


@autocommit
def dao_pin_letter_provider(notification_id, provider, endpoint_url=None):
    # committed before the send, so it's there even if the worker dies during it. An existing pin is for the same
    # provider: the caller checked it
    db.session.execute(
        insert(LetterProviderPin)
        .values(notification_id=notification_id, provider=provider, endpoint_url=endpoint_url)
        .on_conflict_do_nothing()
    )


@autocommit
def dao_unpin_letter_provider(notification_id):
    LetterProviderPin.query.filter_by(notification_id=notification_id).delete()
