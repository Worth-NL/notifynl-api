import uuid
from unittest.mock import ANY

from flask import current_app

from app.dao.organisation_dao import (
    dao_add_user_to_organisation,
)
from app.dao.services_dao import dao_fetch_service_by_id
from tests.app.db import (
    create_user,
)


def test_notify_org_users_of_request_to_go_live(
    mocker,
    admin_request,
    notify_service,
    sample_organisation,
    sample_service,
    organisation_has_new_go_live_request_template,
    organisation_has_new_go_live_request_requester_receipt_template,
    hostnames,
):
    notify_service = dao_fetch_service_by_id(current_app.config["NOTIFY_SERVICE_ID"])

    go_live_user = create_user(email="go-live-user@example.gov.uk", name="Go live user")
    first_org_user = create_user(email="first-org-user@example.gov.uk", name="First org user")
    second_org_user = create_user(email="second-org-user@example.gov.uk", name="Second org user")
    dao_add_user_to_organisation(
        organisation_id=sample_organisation.id, user_id=first_org_user.id, permissions=["can_make_services_live"]
    )
    dao_add_user_to_organisation(
        organisation_id=sample_organisation.id, user_id=second_org_user.id, permissions=["can_make_services_live"]
    )

    org_users_notifications = [object(), object()]
    requester_notification = [object()]

    mock_persist_notification = mocker.patch(
        "app.organisation.sender.persist_notification",
        side_effect=org_users_notifications,
    )
    mock_send_notification_to_queue = mocker.patch(
        "app.organisation.sender.send_notification_to_queue",
    )

    mock_requester_persist_notification = mocker.patch(
        "app.organisation.requester.persist_notification",
        side_effect=requester_notification,
    )
    mock_requester_persist_send_notification_to_queue = mocker.patch(
        "app.organisation.requester.send_notification_to_queue",
    )

    sample_service.organisation = sample_organisation
    sample_service.go_live_user = go_live_user

    admin_request.post(
        "organisation.notify_users_of_request_to_go_live",
        service_id=sample_service.id,
        _expected_status=204,
    )

    assert {
        (call[1]["recipient"], call[1]["personalisation"]["name"]) for call in mock_persist_notification.call_args_list
    } == {
        ("first-org-user@example.gov.uk", "First org user"),
        ("second-org-user@example.gov.uk", "Second org user"),
    }

    assert {
        (call[1]["recipient"], call[1]["personalisation"]["name"])
        for call in mock_requester_persist_notification.call_args_list
    } == {
        ("go-live-user@example.gov.uk", "Go live user"),
    }

    for call in mock_persist_notification.call_args_list:
        assert call[1] == {
            "template_id": uuid.UUID("5c7cfc0f-c3f4-4bd6-9a84-5a144aad5425"),
            "template_version": 1,
            "recipient": ANY,
            "service": notify_service,
            "personalisation": {
                "service_name": "Sample service",
                "requester_name": "Go live user",
                "requester_email_address": "go-live-user@example.gov.uk",
                "make_service_live_link": f"{hostnames.admin}/services/{sample_service.id}/make-service-live",
                "support_page_link": f"{hostnames.admin}/support",
                "organisation_name": "sample organisation",
                "name": ANY,
            },
            "notification_type": "email",
            "api_key_id": None,
            "key_type": "normal",
            "reply_to_text": "go-live-user@example.gov.uk",
        }

    for call in mock_requester_persist_notification.call_args_list:
        assert call[1] == {
            "template_id": uuid.UUID("c7083bfe-1b9a-4ff9-bd5c-30508727df6e"),
            "template_version": 1,
            "recipient": ANY,
            "service": notify_service,
            "personalisation": {
                "service_name": "Sample service",
                "name": "Go live user",
                "organisation_name": "sample organisation",
                "organisation_team_member_names": ["First org user", "Second org user"],
            },
            "notification_type": "email",
            "api_key_id": None,
            "key_type": "normal",
            "reply_to_text": "support@notificatie.nl",
        }

    assert mock_send_notification_to_queue.call_args_list == [
        call(notification, queue="notify-internal-tasks") for notification in org_users_notifications
    ]

    assert mock_requester_persist_send_notification_to_queue.call_args_list == [
        call(notification, queue="notify-internal-tasks") for notification in requester_notification
    ]
