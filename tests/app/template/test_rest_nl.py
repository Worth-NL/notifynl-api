import json

import pytest

from app.constants import EMAIL_TYPE, LETTER_TYPE, SMS_TYPE
from app.models import Template, TemplateHistory
from tests import create_admin_authorization_header
from tests.app.db import (
    create_letter_contact,
    create_service,
    create_template,
)


@pytest.mark.parametrize(
    "template_type, subject",
    [
        (SMS_TYPE, None),
        (EMAIL_TYPE, "subject"),
        (LETTER_TYPE, "subject"),
    ],
)
def test_should_create_a_new_template_for_a_service(client, sample_user, template_type, subject):
    service = create_service(service_permissions=[template_type])
    data = {
        "name": "my template",
        "template_type": template_type,
        "content": "template <b>content</b>",
        "service": str(service.id),
        "created_by": str(sample_user.id),
    }
    if subject:
        data.update({"subject": subject})
    if template_type == LETTER_TYPE:
        data.update({"postage": "netherlands"})
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    response = client.post(
        f"/service/{service.id}/template",
        headers=[("Content-Type", "application/json"), auth_header],
        data=data,
    )
    assert response.status_code == 201
    json_resp = json.loads(response.get_data(as_text=True))
    assert json_resp["data"]["name"] == "my template"
    assert json_resp["data"]["template_type"] == template_type
    assert json_resp["data"]["content"] == "template <b>content</b>"
    assert json_resp["data"]["service"] == str(service.id)
    assert json_resp["data"]["id"]
    assert json_resp["data"]["version"] == 1
    assert json_resp["data"]["created_by"] == str(sample_user.id)
    if subject:
        assert json_resp["data"]["subject"] == "subject"
    else:
        assert not json_resp["data"]["subject"]

    if template_type == LETTER_TYPE:
        assert json_resp["data"]["postage"] == "netherlands"
    else:
        assert not json_resp["data"]["postage"]

    template = Template.query.get(json_resp["data"]["id"])
    from app.schemas import template_schema

    assert sorted(json_resp["data"]) == sorted(template_schema.dump(template))


@pytest.mark.parametrize(
    "template_type, expected_postage", [(SMS_TYPE, None), (EMAIL_TYPE, None), (LETTER_TYPE, "netherlands")]
)
def test_create_a_new_template_for_a_service_adds_postage_for_letters_only(
    client, sample_service, template_type, expected_postage
):
    data = {
        "name": "my template",
        "template_type": template_type,
        "content": "template <b>content</b>",
        "service": str(sample_service.id),
        "created_by": str(sample_service.users[0].id),
    }
    if template_type in [EMAIL_TYPE, LETTER_TYPE]:
        data["subject"] = "Hi, I have good news"

    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    response = client.post(
        f"/service/{sample_service.id}/template",
        headers=[("Content-Type", "application/json"), auth_header],
        data=data,
    )
    assert response.status_code == 201
    template = Template.query.filter(Template.name == "my template").first()
    assert template.postage == expected_postage


@pytest.mark.parametrize(
    "post_data, expected_errors",
    [
        (
            {},
            [
                {"error": "ValidationError", "message": "subject is a required property"},
                {"error": "ValidationError", "message": "name is a required property"},
                {"error": "ValidationError", "message": "template_type is a required property"},
                {"error": "ValidationError", "message": "content is a required property"},
                {"error": "ValidationError", "message": "service is a required property"},
                {"error": "ValidationError", "message": "created_by is a required property"},
            ],
        ),
        (
            {
                "name": "my template",
                "template_type": "sms",
                "content": "hi",
                "postage": "invalid",
                "service": "1af43c02-b5a8-4923-ad7f-5279b75ff2d0",
                "created_by": "30587644-9083-44d8-a114-98887f07f1e3",
            },
            [
                {
                    "error": "ValidationError",
                    "message": "postage invalid. It must be either netherlands, europe or rest-of-world",
                },
            ],
        ),
    ],
)
def test_create_template_validates_against_json_schema(
    admin_request,
    sample_service_full_permissions,
    post_data,
    expected_errors,
):
    response = admin_request.post(
        "template.create_template", service_id=sample_service_full_permissions.id, _data=post_data, _expected_status=400
    )
    assert response["errors"] == expected_errors


def test_create_template_validates_qr_code_too_long(
    admin_request,
    sample_service_full_permissions,
):
    response = admin_request.post(
        "template.create_template",
        service_id=sample_service_full_permissions.id,
        _data={
            "name": "my template",
            "template_type": "letter",
            "subject": "subject",
            "content": "qr: " + ("too long " * 100),
            "postage": "netherlands",
            "service": str(sample_service_full_permissions.id),
            "created_by": "30587644-9083-44d8-a114-98887f07f1e3",
        },
        _expected_status=400,
    )

    assert response == {"result": "error", "message": {"content": ["qr-code-too-long"]}}


def test_update_should_update_a_template(client, sample_user):
    service = create_service(service_permissions=[LETTER_TYPE])
    template = create_template(service, template_type="letter", postage="second")

    assert template.created_by == service.created_by
    assert template.created_by != sample_user

    data = {
        "content": "my template has new content, swell!",
        "created_by": str(sample_user.id),
        "postage": "europe",
    }
    data = json.dumps(data)
    auth_header = create_admin_authorization_header()

    update_response = client.post(
        f"/service/{service.id}/template/{template.id}",
        headers=[("Content-Type", "application/json"), auth_header],
        data=data,
    )

    assert update_response.status_code == 200
    update_json_resp = json.loads(update_response.get_data(as_text=True))
    assert update_json_resp["data"]["content"] == ("my template has new content, swell!")
    assert update_json_resp["data"]["postage"] == "europe"
    assert update_json_resp["data"]["name"] == template.name
    assert update_json_resp["data"]["template_type"] == template.template_type
    assert update_json_resp["data"]["version"] == 2

    assert update_json_resp["data"]["created_by"] == str(sample_user.id)
    template_created_by_users = [template.created_by_id for template in TemplateHistory.query.all()]
    assert len(template_created_by_users) == 2
    assert service.created_by.id in template_created_by_users
    assert sample_user.id in template_created_by_users


def test_create_template_bilingual_letter(admin_request, sample_service_full_permissions, sample_user):
    letter_contact = create_letter_contact(sample_service_full_permissions, "Edinburgh, ED1 1AA")
    json_resp = admin_request.post(
        "template.create_template",
        service_id=sample_service_full_permissions.id,
        _data={
            "name": "my template",
            "template_type": "letter",
            "subject": "subject",
            "content": "content",
            "postage": "netherlands",
            "service": str(sample_service_full_permissions.id),
            "created_by": str(sample_user.id),
            "reply_to": str(letter_contact.id),
            "letter_languages": "welsh_then_english",
            "letter_welsh_subject": "welsh subject",
            "letter_welsh_content": "welsh body",
        },
        _expected_status=201,
    )

    t = Template.query.get(json_resp["data"]["id"])
    assert t.letter_languages == "welsh_then_english"
    assert t.letter_welsh_subject == "welsh subject"
    assert t.letter_welsh_content == "welsh body"
