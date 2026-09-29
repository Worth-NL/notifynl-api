from app import signing
from app.celery.service_callback_tasks import create_delivery_status_callback_data
from tests.app.db import (
    create_notification_history,
    create_service,
    create_service_callback_api,
    create_template,
)


def test_create_delivery_status_callback_data_for_notification_history(notify_db_session):
    # a provider can report back after the notification has moved to notification_history,
    # which has no `to` column
    service = create_service()
    template = create_template(service=service, template_type="letter")
    callback_api = create_service_callback_api(service=service, callback_type="delivery_status")
    notification = create_notification_history(
        template=template, status="delivered", client_reference="my-ref", sent_by="pingen"
    )

    data = signing.decode(create_delivery_status_callback_data(notification, callback_api))

    assert data["notification_id"] == str(notification.id)
    assert data["notification_to"] is None
    assert data["notification_status"] == "delivered"
    assert data["notification_client_reference"] == "my-ref"
