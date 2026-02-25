import uuid
from unittest.mock import Mock

import pytest

from app.constants import (
    KEY_TYPE_NORMAL,
    LETTER_TYPE,
)
from app.models import Notification
from app.service.send_notification import send_one_off_notification
from tests.app.db import (
    create_letter_contact,
    create_service,
    create_template,
)


@pytest.fixture
def persist_mock(mocker):
    noti = Mock(id=uuid.uuid4())
    return mocker.patch("app.service.send_notification.persist_notification", return_value=noti)


@pytest.fixture
def celery_mock(mocker):
    return mocker.patch("app.service.send_notification.send_notification_to_queue")


def test_send_one_off_notification_calls_persist_correctly_for_letter(
    mocker, persist_mock, celery_mock, notify_db_session
):
    mocker.patch(
        "app.service.send_notification.create_random_identifier",
        return_value="this-is-random-in-real-life",
    )
    service = create_service()
    template = create_template(
        service=service,
        template_type=LETTER_TYPE,
        postage="first",
        subject="Test subject",
        content="Hello (( Name))\nYour thing is due soon",
    )

    post_data = {
        "template_id": str(template.id),
        "to": "First Last",
        "personalisation": {
            "name": "foo",
            "address_line_1": "First Last",
            "address_line_2": "1 Example Street",
            "postcode": "1234 AB CityName",
        },
        "created_by": str(service.created_by_id),
    }

    send_one_off_notification(service.id, post_data)

    persist_mock.assert_called_once_with(
        template_id=template.id,
        template_version=template.version,
        recipient=post_data["to"],
        service=template.service,
        personalisation=post_data["personalisation"],
        notification_type=LETTER_TYPE,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        created_by_id=str(service.created_by_id),
        reply_to_text=None,
        reference="this-is-random-in-real-life",
        postage="first",
        client_reference=None,
        template_has_unsubscribe_link=False,
    )


def test_send_one_off_letter_notification_should_use_template_reply_to_text(sample_letter_template, celery_mock):
    letter_contact = create_letter_contact(sample_letter_template.service, "Edinburgh, ED1 1AA", is_default=False)
    sample_letter_template.reply_to = str(letter_contact.id)

    data = {
        "to": "user@example.com",
        "template_id": str(sample_letter_template.id),
        "personalisation": {
            "name": "foo",
            "address_line_1": "First Last",
            "address_line_2": "1 Example Street",
            "address_line_3": "1234 AB cityName",
        },
        "created_by": str(sample_letter_template.service.created_by_id),
    }

    notification_id = send_one_off_notification(service_id=sample_letter_template.service.id, post_data=data)
    notification = Notification.query.get(notification_id["id"])
    celery_mock.assert_called_once_with(notification=notification)

    assert notification.reply_to_text == "Edinburgh, ED1 1AA"
