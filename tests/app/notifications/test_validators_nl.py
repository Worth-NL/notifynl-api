import pytest

from app.constants import (
    EMAIL_TYPE,
    INTERNATIONAL_LETTERS,
    INTERNATIONAL_SMS_TYPE,
    LETTER_TYPE,
    MESSAGEBOX_TYPE,  # noqa: F401
    NOTIFICATION_TYPES,
    SMS_TYPE,
)
from app.notifications.validators import (
    validate_address,
)
from tests.app.db import (
    create_service,
)

NOTIFICATION_TYPES = [SMS_TYPE, EMAIL_TYPE, LETTER_TYPE]  # noqa: F811
NOTIFICATION_TYPES_INT = [SMS_TYPE, EMAIL_TYPE, LETTER_TYPE, INTERNATIONAL_SMS_TYPE]


@pytest.mark.parametrize(
    "key, address_line_3, expected_postage",
    [
        ("address_line_3", "1234 AB City Name", None),
        ("address_line_5", "CANADA", "rest-of-world"),
        ("address_line_3", "GERMANY", "europe"),
    ],
)
def test_validate_address(notify_db_session, key, address_line_3, expected_postage):
    service = create_service(service_permissions=[LETTER_TYPE, INTERNATIONAL_LETTERS])
    data = {
        "address_line_1": "Prince Harry",
        "address_line_2": "Toronto",
        key: address_line_3,
    }
    postage = validate_address(service, data)
    assert postage == expected_postage


def test_validate_address_international_bfpo_no_error(notify_db_session):
    service = create_service(service_permissions=[LETTER_TYPE, INTERNATIONAL_LETTERS])
    data = {
        "address_line_1": "Test User",
        "address_line_2": "Abroad",
        "address_line_3": "BFPO 1234",
        "address_line_4": "USA",
    }
    postage = validate_address(service, data)

    assert postage == "rest-of-world"
