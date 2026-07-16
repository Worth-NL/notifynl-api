import pytest

from app.celery.process_messagebox_client_response_tasks import process_messagebox_client_response
from app.clients import ClientException
from app.constants import MESSAGEBOX_TYPE, NOTIFICATION_SENDING, NOTIFICATION_TECHNICAL_FAILURE
from app.dao.templates_messagebox_dao import get_messagebox_template
from tests.app.db import create_notification, create_service


@pytest.fixture
def messagebox_notification(notify_db_session, notify_user):
    service = create_service(service_permissions=[MESSAGEBOX_TYPE])
    template = get_messagebox_template(service.id)
    return create_notification(template=template, status=NOTIFICATION_SENDING)


def test_process_messagebox_client_response_raises_error_if_reference_is_not_a_valid_uuid():
    with pytest.raises(ValueError):
        process_messagebox_client_response(status="10", provider_reference="not-a-uuid", client_name="ebms-adapter")


def test_process_messagebox_client_response_raises_client_exception_for_unknown_status(messagebox_notification):
    with pytest.raises(ClientException) as e:
        process_messagebox_client_response(
            status="000", provider_reference=str(messagebox_notification.id), client_name="ebms-adapter"
        )

    assert "ebms-adapter callback failed: status 000 not found." in str(e.value)
    assert messagebox_notification.status == NOTIFICATION_TECHNICAL_FAILURE


def test_process_messagebox_client_response_success_persists_verwerkt_and_stadium(messagebox_notification):
    process_messagebox_client_response(
        status="10",
        provider_reference=str(messagebox_notification.id),
        client_name="ebms-adapter",
        detailed_status_code="Verwerkt",
        stadium="NA",
    )

    assert messagebox_notification.status == "delivered"
    assert messagebox_notification.detailed_status_code == "Verwerkt"
    assert messagebox_notification.messagebox_stadium == "NA"


def test_process_messagebox_client_response_failure_persists_code_and_stadium(messagebox_notification):
    process_messagebox_client_response(
        status="20",
        provider_reference=str(messagebox_notification.id),
        client_name="ebms-adapter",
        detailed_status_code="BerichtBestaatAl",
        stadium="StoreMessage",
    )

    assert messagebox_notification.status == "permanent-failure"
    assert messagebox_notification.detailed_status_code == "BerichtBestaatAl"
    assert messagebox_notification.messagebox_stadium == "StoreMessage"


def test_process_messagebox_client_response_queues_callback_task(messagebox_notification, mocker):
    mock_callback = mocker.patch("app.celery.process_messagebox_client_response_tasks.check_and_queue_callback_task")

    process_messagebox_client_response(
        status="10",
        provider_reference=str(messagebox_notification.id),
        client_name="ebms-adapter",
        detailed_status_code="Verwerkt",
        stadium="NA",
    )

    mock_callback.assert_called_once_with(messagebox_notification)
