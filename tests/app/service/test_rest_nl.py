import json

import pytest
from flask import url_for

from tests import create_admin_authorization_header


def test_create_pdf_letter(mocker, sample_service_full_permissions, client, fake_uuid, notify_user):
    mocker.patch("app.service.send_notification.utils_s3download")
    mocker.patch("app.service.send_notification.get_page_count", return_value=1)
    mocker.patch("app.service.send_notification.move_uploaded_pdf_to_letters_bucket")

    user = sample_service_full_permissions.users[0]
    data = json.dumps(
        {
            "filename": "valid.pdf",
            "created_by": str(user.id),
            "file_id": fake_uuid,
            "postage": "netherlands",
            "recipient_address": "User%20Name%0AStreet%20Name%20and%20Number%201%0A1234%20PC%20Looney%20Town",
        }
    )

    response = client.post(
        url_for("service.create_pdf_letter", service_id=sample_service_full_permissions.id),
        data=data,
        headers=[("Content-Type", "application/json"), create_admin_authorization_header()],
    )
    json_resp = json.loads(response.get_data(as_text=True))

    assert response.status_code == 201
    assert json_resp == {"id": fake_uuid}


@pytest.mark.parametrize(
    "post_data, expected_errors",
    [
        (
            {},
            [
                {"error": "ValidationError", "message": "postage is a required property"},
                {"error": "ValidationError", "message": "filename is a required property"},
                {"error": "ValidationError", "message": "created_by is a required property"},
                {"error": "ValidationError", "message": "file_id is a required property"},
                {"error": "ValidationError", "message": "recipient_address is a required property"},
            ],
        ),
        (
            {
                "postage": "third",
                "filename": "string",
                "created_by": "string",
                "file_id": "string",
                "recipient_address": "Some Address",
            },
            [
                {
                    "error": "ValidationError",
                    "message": "postage invalid. It must be netherlands, europe or rest-of-world",
                }
            ],
        ),
    ],
)
def test_create_pdf_letter_validates_against_json_schema(
    sample_service_full_permissions, client, post_data, expected_errors
):
    response = client.post(
        url_for("service.create_pdf_letter", service_id=sample_service_full_permissions.id),
        data=json.dumps(post_data),
        headers=[("Content-Type", "application/json"), create_admin_authorization_header()],
    )
    json_resp = json.loads(response.get_data(as_text=True))

    assert response.status_code == 400
    assert json_resp["errors"] == expected_errors
