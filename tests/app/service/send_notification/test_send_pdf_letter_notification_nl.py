import pytest
from freezegun import freeze_time

from app.constants import LETTER_TYPE
from app.dao.notifications_dao import get_notification_by_id
from app.service.send_notification import send_pdf_letter_notification


@pytest.fixture
def post_data(sample_service_full_permissions, fake_uuid):
    return {
        "filename": "valid.pdf",
        "created_by": sample_service_full_permissions.users[0].id,
        "file_id": fake_uuid,
        "postage": "netherlands",
        "recipient_address": "User%20Name%0AStreet%20Name%20and%20Number%201%0A1234%20PC%20Looney%20Town",
    }


@freeze_time("2019-08-02 11:00:00")
def test_send_pdf_letter_notification_creates_notification_and_moves_letter(
    mocker,
    sample_service_full_permissions,
    notify_user,
    post_data,
):
    mocker.patch("app.service.send_notification.utils_s3download")
    mocker.patch("app.service.send_notification.get_page_count", return_value=1)
    s3_mock = mocker.patch("app.service.send_notification.move_uploaded_pdf_to_letters_bucket")

    result = send_pdf_letter_notification(sample_service_full_permissions.id, post_data)
    file_id = post_data["file_id"]

    notification = get_notification_by_id(file_id)

    assert str(notification.id) == file_id
    assert notification.api_key_id is None
    assert notification.client_reference == post_data["filename"]
    assert notification.created_by_id == post_data["created_by"]
    assert notification.postage == "netherlands"
    assert notification.notification_type == LETTER_TYPE
    assert notification.billable_units == 1
    assert notification.to == "User Name\nStreet Name and Number 1\n1234 PC Looney Town"

    assert notification.service_id == sample_service_full_permissions.id
    assert result == {"id": str(notification.id)}

    s3_mock.assert_called_once_with(
        f"service-{sample_service_full_permissions.id}/{file_id}.pdf",
        f"2019-08-02/NOTIFY.{notification.reference}.D.1.C.20190802110000.PDF",
    )
