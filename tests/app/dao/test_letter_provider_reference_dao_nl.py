import uuid

from app.dao.letter_provider_reference_dao import (
    dao_create_letter_provider_reference,
    dao_get_letter_provider_pin,
    dao_get_letter_provider_reference,
    dao_get_notification_id_by_provider_reference,
    dao_pin_letter_provider,
    dao_unpin_letter_provider,
)


def test_create_and_get_letter_provider_reference(notify_db_session):
    notification_id = uuid.uuid4()

    dao_create_letter_provider_reference(notification_id, "pingen", "pingen-letter-1")
    dao_create_letter_provider_reference(notification_id, "pingen", "pingen-letter-1")  # e.g. a retried delivery

    reference = dao_get_letter_provider_reference(notification_id)
    assert (reference.provider, reference.provider_reference) == ("pingen", "pingen-letter-1")
    assert dao_get_notification_id_by_provider_reference("pingen", "pingen-letter-1") == notification_id


def test_get_letter_provider_reference_when_there_is_none(notify_db_session):
    assert dao_get_letter_provider_reference(uuid.uuid4()) is None
    assert dao_get_notification_id_by_provider_reference("pingen", "unknown") is None
    assert dao_get_notification_id_by_provider_reference("rest-endpoint", "pingen-letter-1") is None


def test_pin_and_unpin_letter_provider(notify_db_session):
    notification_id = uuid.uuid4()

    dao_pin_letter_provider(notification_id, "rest-endpoint", "https://print.example.com/letters")
    dao_pin_letter_provider(notification_id, "rest-endpoint", "https://print.example.com/letters")  # a retry

    pin = dao_get_letter_provider_pin(notification_id)
    assert (pin.provider, pin.endpoint_url) == ("rest-endpoint", "https://print.example.com/letters")

    dao_unpin_letter_provider(notification_id)
    dao_unpin_letter_provider(notification_id)

    assert dao_get_letter_provider_pin(notification_id) is None


def test_pin_letter_provider_keeps_the_first_pin(notify_db_session):
    notification_id = uuid.uuid4()

    dao_pin_letter_provider(notification_id, "pingen")
    dao_pin_letter_provider(notification_id, "rest-endpoint", "https://print.example.com/letters")

    pin = dao_get_letter_provider_pin(notification_id)
    assert (pin.provider, pin.endpoint_url) == ("pingen", None)
