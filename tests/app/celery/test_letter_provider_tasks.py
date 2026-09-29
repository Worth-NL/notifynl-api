from datetime import date, datetime
from unittest import mock

import pytest
from celery.exceptions import MaxRetriesExceededError, Retry
from freezegun import freeze_time

from app import signing
from app.celery.letter_provider_tasks import (
    check_letters_stuck_sending,
    deliver_letter_via_provider,
    dispatch_stranded_letters,
    process_letter_provider_status,
    queue_letter_for_delivery,
)
from app.clients.letter import (
    LetterClientNonRetryableException,
    LetterClientRetryableException,
    LetterSendResult,
)
from app.clients.letter.pingen import PingenClient
from app.clients.letter.rest_endpoint import RestEndpointLetterClient
from app.dao.letter_provider_reference_dao import dao_get_letter_provider_reference
from app.letters.utils import LetterPDFNotFound
from app.models import LetterCostThreshold, Notification, NotificationHistory, NotificationLetterDespatch
from tests.app.db import (
    create_notification,
    create_notification_history,
    create_organisation,
    create_service,
    create_template,
)
from tests.app.db_nl import create_letter_provider_reference, create_organisation_letter_provider
from tests.conftest import set_config, set_config_values

PDF = b"%PDF-1.7 letter"


@pytest.fixture
def organisation(notify_db_session):
    return create_organisation()


@pytest.fixture
def letter_template(organisation):
    service = create_service(organisation=organisation, service_name="letter service")
    return create_template(service=service, template_type="letter", postage="netherlands")


@pytest.fixture
def letter_notification(letter_template):
    return create_notification(
        template=letter_template,
        status="created",
        billable_units=1,
        reference="GENERATEDREF",
        client_reference="MY-REF",
    )


@pytest.fixture
def pdf_in_s3(mocker):
    s3_object = mock.Mock()
    s3_object.get.return_value = {"Body": mock.Mock(read=mock.Mock(return_value=PDF))}
    return mocker.patch("app.celery.letter_provider_tasks.find_letter_pdf_in_s3", return_value=s3_object)


@pytest.fixture
def send_with_pingen(mocker):
    return mocker.patch.object(
        PingenClient, "send_letter", autospec=True, return_value=LetterSendResult(provider_reference="pingen-1")
    )


@pytest.fixture
def send_with_rest_endpoint(mocker):
    return mocker.patch.object(
        RestEndpointLetterClient, "send_letter", autospec=True, return_value=LetterSendResult(provider_reference=None)
    )


@pytest.fixture
def mock_callback(mocker):
    return mocker.patch("app.celery.letter_provider_tasks.check_and_queue_callback_task")


def _status(notification):
    return Notification.query.get(notification.id).status


@freeze_time("2026-09-29 12:00")
def test_deliver_letter_via_provider_sends_with_pingen_by_default(
    notify_api, letter_notification, pdf_in_s3, send_with_pingen, mock_callback
):
    with set_config(notify_api, "API_HOST_NAME", "https://api.notifynl.nl"):
        deliver_letter_via_provider(str(letter_notification.id))

    (_client, letter, letter_provider), _ = send_with_pingen.call_args
    assert letter.notification_id == str(letter_notification.id)
    assert letter.reference == "GENERATEDREF"
    assert letter.organisation_id == str(letter_notification.service.organisation_id)
    assert letter.pdf == PDF
    assert letter.postage == "netherlands"
    assert letter.callback_url == (
        "https://api.notifynl.nl/notifications/letter/provider-status"
        f"?token={signing.encode(str(letter_notification.id))}"
    )
    assert letter_provider is None

    notification = Notification.query.get(letter_notification.id)
    assert (notification.status, notification.sent_by) == ("sent", "pingen")
    assert notification.sent_at == datetime(2026, 9, 29, 12, 0)
    assert dao_get_letter_provider_reference(letter_notification.id).provider_reference == "pingen-1"
    assert mock_callback.call_args.args[0].id == letter_notification.id


def test_deliver_letter_via_provider_sends_with_the_organisations_rest_endpoint(
    letter_notification, organisation, pdf_in_s3, send_with_rest_endpoint, send_with_pingen, mock_callback
):
    letter_provider = create_organisation_letter_provider(
        organisation,
        "rest-endpoint",
        endpoint_url="https://print.example.com",
        auth_method="api_key",
        auth_config={"api_key_header": "X-Api-Key", "api_key": "k"},
    )

    deliver_letter_via_provider(str(letter_notification.id))

    assert not send_with_pingen.called
    assert send_with_rest_endpoint.call_args.args[2] == letter_provider
    assert Notification.query.get(letter_notification.id).sent_by == "rest-endpoint"
    # the endpoint didn't return an id
    assert dao_get_letter_provider_reference(letter_notification.id) is None


@pytest.mark.parametrize(
    "send_client_reference, client_reference, expected_reference",
    [
        (True, "MY-REF", "MY-REF"),
        (True, None, "GENERATEDREF"),
        (False, "MY-REF", "GENERATEDREF"),
    ],
)
def test_deliver_letter_via_provider_sends_the_client_reference_when_the_service_asks_for_it(
    letter_template,
    pdf_in_s3,
    send_with_pingen,
    mock_callback,
    send_client_reference,
    client_reference,
    expected_reference,
):
    letter_template.service.send_client_reference_to_letter_provider = send_client_reference
    notification = create_notification(
        template=letter_template, status="created", reference="GENERATEDREF", client_reference=client_reference
    )

    deliver_letter_via_provider(str(notification.id))

    assert send_with_pingen.call_args.args[1].reference == expected_reference


def test_deliver_letter_via_provider_sends_a_letter_only_once(
    letter_notification, pdf_in_s3, send_with_pingen, mock_callback
):
    deliver_letter_via_provider(str(letter_notification.id))
    # e.g. the hook and the sweep both queued it, or SQS delivered the message twice
    deliver_letter_via_provider(str(letter_notification.id))

    assert send_with_pingen.call_count == 1


def test_deliver_letter_via_provider_does_not_send_a_letter_another_task_is_sending(
    letter_notification, pdf_in_s3, send_with_pingen
):
    letter_notification.status = "sending"

    deliver_letter_via_provider(str(letter_notification.id))

    assert not send_with_pingen.called


def test_deliver_letter_via_provider_retry_continues_sending_the_letter_it_claimed(
    letter_notification, pdf_in_s3, send_with_pingen, mock_callback
):
    letter_notification.status = "sending"

    deliver_letter_via_provider.push_request(retries=1)
    try:
        deliver_letter_via_provider.run(str(letter_notification.id))
    finally:
        deliver_letter_via_provider.pop_request()

    assert send_with_pingen.called
    assert _status(letter_notification) == "sent"


def test_deliver_letter_via_provider_skips_a_letter_being_delivered_under_the_lock(
    letter_notification, pdf_in_s3, send_with_pingen, mocker
):
    mocker.patch("app.celery.letter_provider_tasks.redis_store.get_lock").return_value.acquire.return_value = False

    deliver_letter_via_provider(str(letter_notification.id))

    assert not send_with_pingen.called


@pytest.mark.parametrize("key_type", ["test", "team"])
def test_deliver_letter_via_provider_never_sends_test_letters(letter_template, pdf_in_s3, send_with_pingen, key_type):
    notification = create_notification(template=letter_template, status="created", key_type=key_type)

    deliver_letter_via_provider(str(notification.id))

    assert not send_with_pingen.called
    assert _status(notification) == "created"


def test_deliver_letter_via_provider_for_unknown_notification(notify_db_session, send_with_pingen):
    deliver_letter_via_provider("f0ffb2d9-e4df-4ee2-9d2a-000000000000")

    assert not send_with_pingen.called


def test_deliver_letter_via_provider_retries_when_the_provider_is_unavailable(
    letter_notification, pdf_in_s3, send_with_pingen, mock_callback, mocker
):
    send_with_pingen.side_effect = LetterClientRetryableException("down")
    retry = mocker.patch.object(deliver_letter_via_provider, "retry", side_effect=Retry)

    with freeze_time("2026-09-29 12:03"), pytest.raises(Retry):
        deliver_letter_via_provider(str(letter_notification.id))

    assert retry.called
    notification = Notification.query.get(letter_notification.id)
    assert notification.status == "sending"
    assert notification.updated_at == datetime(2026, 9, 29, 12, 3)
    assert not mock_callback.called


def test_deliver_letter_via_provider_fails_the_letter_after_the_last_retry(
    letter_notification, pdf_in_s3, send_with_pingen, mock_callback, mocker
):
    send_with_pingen.side_effect = LetterClientRetryableException("down")
    mocker.patch.object(deliver_letter_via_provider, "retry", side_effect=MaxRetriesExceededError)

    deliver_letter_via_provider(str(letter_notification.id))

    notification = Notification.query.get(letter_notification.id)
    assert (notification.status, notification.detailed_status_code) == (
        "technical-failure",
        "print-provider-unavailable",
    )
    assert mock_callback.called


def test_deliver_letter_via_provider_fails_a_rejected_letter(
    letter_notification, pdf_in_s3, send_with_pingen, mock_callback, mocker
):
    send_with_pingen.side_effect = LetterClientNonRetryableException("rejected", "pingen-http-422")
    retry = mocker.patch.object(deliver_letter_via_provider, "retry")

    deliver_letter_via_provider(str(letter_notification.id))

    notification = Notification.query.get(letter_notification.id)
    assert (notification.status, notification.detailed_status_code) == ("technical-failure", "pingen-http-422")
    assert not retry.called
    assert mock_callback.called


def test_deliver_letter_via_provider_retries_until_the_pdf_is_there(
    letter_notification, pdf_in_s3, send_with_pingen, mocker
):
    pdf_in_s3.side_effect = LetterPDFNotFound
    mocker.patch.object(deliver_letter_via_provider, "retry", side_effect=Retry)

    with pytest.raises(Retry):
        deliver_letter_via_provider(str(letter_notification.id))

    assert not send_with_pingen.called
    assert _status(letter_notification) == "sending"


def test_deliver_letter_via_provider_fails_letters_of_services_without_an_organisation(
    notify_db_session, pdf_in_s3, send_with_pingen, mock_callback
):
    template = create_template(service=create_service(service_name="no organisation"), template_type="letter")
    notification = create_notification(template=template, status="created")

    deliver_letter_via_provider(str(notification.id))

    assert not send_with_pingen.called
    notification = Notification.query.get(notification.id)
    assert (notification.status, notification.detailed_status_code) == ("technical-failure", "no-organisation")


def test_deliver_letter_via_provider_does_not_resend_a_letter_the_provider_already_accepted(
    letter_notification, pdf_in_s3, send_with_pingen, mock_callback
):
    # a previous attempt got the letter accepted, but failed before marking it sent
    letter_notification.status = "sending"
    create_letter_provider_reference(letter_notification.id, "pingen", "pingen-1")

    deliver_letter_via_provider.push_request(retries=1)
    try:
        deliver_letter_via_provider.run(str(letter_notification.id))
    finally:
        deliver_letter_via_provider.pop_request()

    assert not send_with_pingen.called
    assert _status(letter_notification) == "sent"


def test_deliver_letter_via_provider_keeps_a_status_the_provider_already_reported(
    letter_notification, pdf_in_s3, send_with_pingen, mock_callback
):
    def provider_reports_back_before_responding(client, letter, letter_provider):
        # like notifynl-dvla-service did: the provider's callback arrives before its response
        Notification.query.filter_by(id=letter_notification.id).update({"status": "delivered"})
        return LetterSendResult()

    send_with_pingen.side_effect = provider_reports_back_before_responding

    deliver_letter_via_provider(str(letter_notification.id))

    assert _status(letter_notification) == "delivered"
    assert not mock_callback.called


@pytest.mark.parametrize(
    "enabled, key_type, expected_queued",
    [
        (True, "normal", True),
        (False, "normal", False),
        (True, "test", False),
    ],
)
def test_queue_letter_for_delivery(notify_api, letter_template, mocker, enabled, key_type, expected_queued):
    apply_async = mocker.patch("app.celery.letter_provider_tasks.deliver_letter_via_provider.apply_async")
    notification = create_notification(template=letter_template, status="created", key_type=key_type)

    with set_config(notify_api, "LETTER_DELIVERY_VIA_PROVIDERS", enabled):
        queue_letter_for_delivery(notification)

    if expected_queued:
        apply_async.assert_called_once_with(
            [str(notification.id)], queue="send-letter-tasks", MessageGroupId=str(notification.service_id)
        )
    else:
        assert not apply_async.called


@freeze_time("2026-09-29 12:00")
def test_dispatch_stranded_letters_queues_letters_ready_for_a_while(notify_api, letter_template, mocker):
    apply_async = mocker.patch("app.celery.letter_provider_tasks.deliver_letter_via_provider.apply_async")
    stranded = create_notification(template=letter_template, status="created", created_at=datetime(2026, 9, 29, 11))
    create_notification(template=letter_template, status="created", created_at=datetime(2026, 9, 29, 11, 50))

    with set_config(notify_api, "LETTER_DELIVERY_VIA_PROVIDERS", True):
        dispatch_stranded_letters()

    apply_async.assert_called_once_with([str(stranded.id)], queue="send-letter-tasks")


def test_dispatch_stranded_letters_does_nothing_while_letters_go_through_dvla(notify_api, letter_template, mocker):
    apply_async = mocker.patch("app.celery.letter_provider_tasks.deliver_letter_via_provider.apply_async")
    create_notification(template=letter_template, status="created", created_at=datetime(2020, 1, 1))

    with set_config(notify_api, "LETTER_DELIVERY_VIA_PROVIDERS", False):
        dispatch_stranded_letters()

    assert not apply_async.called


@freeze_time("2026-09-29 12:00")
def test_check_letters_stuck_sending_raises_one_ticket(notify_api, letter_template, mocker):
    send_ticket = mocker.patch("app.celery.letter_provider_tasks.zendesk_client.send_ticket_to_zendesk")
    stuck = [
        create_notification(
            template=letter_template,
            status="sending",
            created_at=datetime(2026, 9, 29, 6),
            updated_at=datetime(2026, 9, 29, 6),
        )
        for _ in range(2)
    ]
    create_notification(
        template=letter_template,
        status="sending",
        created_at=datetime(2026, 9, 29, 11),
        updated_at=datetime(2026, 9, 29, 11),
    )

    with set_config_values(notify_api, {"NOTIFY_ENVIRONMENT": "test", "SEND_ZENDESK_ALERTS_ENABLED": True}):
        check_letters_stuck_sending()

    send_ticket.assert_called_once()
    ticket = send_ticket.call_args.args[0]
    assert ticket.subject == "[test] Letters stuck sending to their print provider"
    for notification in stuck:
        assert str(notification.id) in ticket.message


def test_check_letters_stuck_sending_without_stuck_letters(notify_api, letter_template, mocker):
    send_ticket = mocker.patch("app.celery.letter_provider_tasks.zendesk_client.send_ticket_to_zendesk")
    create_notification(template=letter_template, status="sent", created_at=datetime(2020, 1, 1))

    check_letters_stuck_sending()

    assert not send_ticket.called


@freeze_time("2026-09-29 12:00")
@pytest.mark.parametrize("from_status", ["sending", "sent"])
def test_process_letter_provider_status_delivered(letter_template, mock_callback, from_status):
    notification = create_notification(template=letter_template, status=from_status)

    process_letter_provider_status(str(notification.id), "pingen", "delivered")

    notification = Notification.query.get(notification.id)
    assert notification.status == "delivered"
    despatch = NotificationLetterDespatch.query.get(notification.id)
    assert (despatch.despatched_on, despatch.cost_threshold) == (date(2026, 9, 29), LetterCostThreshold.unsorted)
    mock_callback.assert_called_once_with(notification)


@pytest.mark.parametrize(
    "status, detailed_status_code",
    [("technical-failure", "print-provider-issue"), ("permanent-failure", "print-provider-rejected")],
)
def test_process_letter_provider_status_failure(letter_template, mock_callback, status, detailed_status_code):
    notification = create_notification(template=letter_template, status="sent")

    process_letter_provider_status(str(notification.id), "pingen", status, reason="Content failed inspection")

    notification = Notification.query.get(notification.id)
    assert (notification.status, notification.detailed_status_code) == (status, detailed_status_code)
    assert mock_callback.called


@pytest.mark.parametrize(
    "from_status, status",
    [
        ("delivered", "delivered"),  # a duplicate report
        ("delivered", "technical-failure"),
        ("technical-failure", "delivered"),
        ("created", "delivered"),
        ("returned-letter", "returned-letter"),
    ],
)
def test_process_letter_provider_status_never_moves_a_letter_backwards(
    letter_template, mock_callback, mocker, from_status, status
):
    returned = mocker.patch("app.celery.tasks.process_returned_letters_list")
    notification = create_notification(template=letter_template, status=from_status)

    process_letter_provider_status(str(notification.id), "rest-endpoint", status)

    assert _status(notification) == from_status
    assert not mock_callback.called
    assert not returned.called


@pytest.mark.parametrize("from_status", ["sent", "delivered"])
def test_process_letter_provider_status_returned_letter(letter_template, mock_callback, mocker, from_status):
    returned = mocker.patch("app.celery.tasks.process_returned_letters_list")
    notification = create_notification(template=letter_template, status=from_status, reference="RETURNEDREF")

    process_letter_provider_status(str(notification.id), "pingen", "returned-letter", reason="Moved away")

    # also records the returned letter for the service's report and sends the returned letter callback
    returned.assert_called_once_with(["RETURNEDREF"])
    assert not mock_callback.called


def test_process_letter_provider_status_for_a_letter_in_notification_history(letter_template, mock_callback):
    notification = create_notification_history(template=letter_template, status="sent")

    process_letter_provider_status(str(notification.id), "pingen", "delivered")

    assert NotificationHistory.query.get(notification.id).status == "delivered"
    assert mock_callback.called
