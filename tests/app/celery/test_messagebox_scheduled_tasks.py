from datetime import datetime, timedelta

import pytest
from ebms_adapter_client.berichtenbox import ParsedBericht, ParsedBerichtenBatch
from ebms_adapter_client.models import DataSource, EbMSMessageStatus, Message, MessageProperties, Party

from app.celery import messagebox_scheduled_tasks
from app.celery.messagebox_scheduled_tasks import (
    MESSAGEBOX_NIL_BERICHT_ID,
    MESSAGEBOX_STATUS_DELIVERED,
    MESSAGEBOX_STATUS_FAILED,
    check_if_messagebox_still_pending,
    messagebox_process_unprocessed_messages,
)
from app.config import QueueNamesNL, TaskNamesNL
from app.constants import MESSAGEBOX_TYPE, NOTIFICATION_CREATED, NOTIFICATION_PENDING_VIRUS_CHECK, NOTIFICATION_SENDING
from app.dao.templates_messagebox_dao import get_messagebox_template
from tests.app.db import create_notification, create_service


@pytest.fixture
def messagebox_notification(notify_db_session, notify_user):
    service = create_service(service_permissions=[MESSAGEBOX_TYPE])
    template = get_messagebox_template(service.id)
    return create_notification(template=template, status=NOTIFICATION_SENDING)


@pytest.fixture(autouse=True)
def ebms_adapter_url_config():
    # "test" (as opposed to "testnl") config doesn't define this NL-only key.
    messagebox_scheduled_tasks.current_app.config["EBMS_ADAPTER_URL"] = "http://ebms-adapter.local"


def _batch(*, total_received: int, successful_count: int, messages: list[ParsedBericht]) -> ParsedBerichtenBatch:
    return ParsedBerichtenBatch(
        batch_id="batch-1",
        berichtleverancier_code="00000000000000000000",
        total_received=total_received,
        successful_count=successful_count,
        geen_actieve_box_of_geabonneerd_count=0,
        technisch_probleem_count=0,
        bericht_type_niet_correct_count=0,
        publicatie_datum_niet_correct_count=0,
        aanmaak_datum_niet_correct_count=0,
        datum_ontvangen=datetime(2024, 1, 1, 9, 0, 0),
        datum_verwerkt=datetime(2024, 1, 1, 9, 1, 30),
        messages=messages,
    )


def _message(content: bytes) -> Message:
    return Message(
        properties=MessageProperties(
            cpa_id="cpa-1",
            from_party=Party(party_id="from"),
            to_party=Party(party_id="to"),
            service="service",
            action="action",
            timestamp=None,
            conversation_id="conv-1",
            message_id="envelope-1",
            message_status=EbMSMessageStatus.DELIVERED,
        ),
        data_sources=[DataSource(content_type="text/xml", content=content)],
    )


def test_messagebox_process_unprocessed_messages_dispatches_delivered_and_marks_processed(mocker):
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsAdapterClientConfig")
    mock_core_client = mocker.Mock()
    mock_core_client.__enter__ = mocker.Mock(return_value=mock_core_client)
    mock_core_client.__exit__ = mocker.Mock(return_value=False)
    mock_core_client.list_unprocessed_message_ids.return_value = ["envelope-1"]
    mock_core_client.get_message.return_value = _message(b"<BerichtVerwerkResponse/>")
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsCoreClient", return_value=mock_core_client)
    mocker.patch(
        "app.celery.messagebox_scheduled_tasks.parse_berichten_verwerk_response",
        return_value=_batch(
            total_received=1,
            successful_count=1,
            messages=[ParsedBericht(message_id="notif-1", process_code="00", bericht_type="bericht", stadium="NA")],
        ),
    )
    mock_apply_async = mocker.patch(
        "app.celery.messagebox_scheduled_tasks.process_messagebox_client_response.apply_async"
    )

    messagebox_process_unprocessed_messages()

    mock_apply_async.assert_called_once_with(
        [MESSAGEBOX_STATUS_DELIVERED, "notif-1", "ebms-adapter", "00", "NA", "envelope-1"],
        queue=QueueNamesNL.MESSAGEBOX_CALLBACKS,
    )
    mock_core_client.process_message.assert_called_once_with("envelope-1")


def test_messagebox_process_unprocessed_messages_logs_envelope_summary(mocker, caplog):
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsAdapterClientConfig")
    mock_core_client = mocker.Mock()
    mock_core_client.__enter__ = mocker.Mock(return_value=mock_core_client)
    mock_core_client.__exit__ = mocker.Mock(return_value=False)
    mock_core_client.list_unprocessed_message_ids.return_value = ["envelope-1"]
    mock_core_client.get_message.return_value = _message(b"<BerichtVerwerkResponse/>")
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsCoreClient", return_value=mock_core_client)
    mocker.patch(
        "app.celery.messagebox_scheduled_tasks.parse_berichten_verwerk_response",
        return_value=_batch(
            total_received=1,
            successful_count=1,
            messages=[ParsedBericht(message_id="notif-1", process_code="00", bericht_type="bericht", stadium="NA")],
        ),
    )
    mocker.patch("app.celery.messagebox_scheduled_tasks.process_messagebox_client_response.apply_async")

    with caplog.at_level("INFO"):
        messagebox_process_unprocessed_messages()

    summary_records = [r for r in caplog.records if "poll cycle complete" in r.message]
    assert len(summary_records) == 1
    assert summary_records[0].envelope_id == "envelope-1"
    assert summary_records[0].message_ids == ["notif-1"]
    assert summary_records[0].all_dispatched is True
    assert summary_records[0].acked is True


def test_messagebox_process_unprocessed_messages_failed_batch_status(mocker):
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsAdapterClientConfig")
    mock_core_client = mocker.Mock()
    mock_core_client.__enter__ = mocker.Mock(return_value=mock_core_client)
    mock_core_client.__exit__ = mocker.Mock(return_value=False)
    mock_core_client.list_unprocessed_message_ids.return_value = ["envelope-1"]
    mock_core_client.get_message.return_value = _message(b"<BerichtVerwerkResponse/>")
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsCoreClient", return_value=mock_core_client)
    mocker.patch(
        "app.celery.messagebox_scheduled_tasks.parse_berichten_verwerk_response",
        return_value=_batch(
            total_received=1,
            successful_count=0,
            messages=[
                ParsedBericht(
                    message_id="notif-1", process_code="TechnischProbleem", bericht_type="bericht", stadium="NA"
                )
            ],
        ),
    )
    mock_apply_async = mocker.patch(
        "app.celery.messagebox_scheduled_tasks.process_messagebox_client_response.apply_async"
    )

    messagebox_process_unprocessed_messages()

    mock_apply_async.assert_called_once_with(
        [MESSAGEBOX_STATUS_FAILED, "notif-1", "ebms-adapter", "TechnischProbleem", "NA", "envelope-1"],
        queue=QueueNamesNL.MESSAGEBOX_CALLBACKS,
    )


def test_messagebox_process_unprocessed_messages_resolves_nil_bericht_id_via_batch_id(mocker, caplog):
    # Logius echoes a nil BerichtID when it can't parse/validate the submitted message
    # (e.g. OinInCPAKomtNietOvereenMetOinInBericht) -- BatchID (which notifynl-api sets to
    # the notification id at send time) is the fallback correlation key in that case.
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsAdapterClientConfig")
    mock_core_client = mocker.Mock()
    mock_core_client.__enter__ = mocker.Mock(return_value=mock_core_client)
    mock_core_client.__exit__ = mocker.Mock(return_value=False)
    mock_core_client.list_unprocessed_message_ids.return_value = ["envelope-1"]
    mock_core_client.get_message.return_value = _message(b"<BerichtVerwerkResponse/>")
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsCoreClient", return_value=mock_core_client)
    mocker.patch(
        "app.celery.messagebox_scheduled_tasks.parse_berichten_verwerk_response",
        return_value=_batch(
            total_received=1,
            successful_count=0,
            messages=[
                ParsedBericht(
                    message_id=MESSAGEBOX_NIL_BERICHT_ID,
                    process_code="OinInCPAKomtNietOvereenMetOinInBericht",
                    bericht_type="Onbekend",
                    stadium="ValidatieBerichtType",
                )
            ],
        ),
    )
    mock_apply_async = mocker.patch(
        "app.celery.messagebox_scheduled_tasks.process_messagebox_client_response.apply_async"
    )

    with caplog.at_level("INFO"):
        messagebox_process_unprocessed_messages()

    # _batch()'s default batch_id is "batch-1" -- resolved in place of the nil BerichtID.
    mock_apply_async.assert_called_once_with(
        [
            MESSAGEBOX_STATUS_FAILED,
            "batch-1",
            "ebms-adapter",
            "OinInCPAKomtNietOvereenMetOinInBericht",
            "ValidatieBerichtType",
            "envelope-1",
        ],
        queue=QueueNamesNL.MESSAGEBOX_CALLBACKS,
    )
    resolved_records = [r for r in caplog.records if "resolved via batch_id" in r.message]
    assert len(resolved_records) == 1
    assert resolved_records[0].resolved_message_id == "batch-1"


def test_messagebox_process_unprocessed_messages_leaves_envelope_unprocessed_on_parse_failure(mocker, caplog):
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsAdapterClientConfig")
    mock_core_client = mocker.Mock()
    mock_core_client.__enter__ = mocker.Mock(return_value=mock_core_client)
    mock_core_client.__exit__ = mocker.Mock(return_value=False)
    mock_core_client.list_unprocessed_message_ids.return_value = ["envelope-1"]
    mock_core_client.get_message.side_effect = Exception("network error")
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsCoreClient", return_value=mock_core_client)
    mock_apply_async = mocker.patch(
        "app.celery.messagebox_scheduled_tasks.process_messagebox_client_response.apply_async"
    )
    mock_statsd_incr = mocker.patch("app.celery.messagebox_scheduled_tasks.statsd_client.incr")

    with caplog.at_level("ERROR"):
        messagebox_process_unprocessed_messages()

    mock_apply_async.assert_not_called()
    mock_core_client.process_message.assert_not_called()
    mock_statsd_incr.assert_called_once_with("messagebox.envelope-fetch-parse-failure")
    fetch_failure_records = [r for r in caplog.records if "Failed to fetch/parse" in r.message]
    assert len(fetch_failure_records) == 1
    assert fetch_failure_records[0].envelope_id == "envelope-1"
    assert fetch_failure_records[0].exception_type == "Exception"


def test_messagebox_process_unprocessed_messages_leaves_envelope_unprocessed_on_dispatch_failure(mocker):
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsAdapterClientConfig")
    mock_core_client = mocker.Mock()
    mock_core_client.__enter__ = mocker.Mock(return_value=mock_core_client)
    mock_core_client.__exit__ = mocker.Mock(return_value=False)
    mock_core_client.list_unprocessed_message_ids.return_value = ["envelope-1"]
    mock_core_client.get_message.return_value = _message(b"<BerichtVerwerkResponse/>")
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsCoreClient", return_value=mock_core_client)
    mocker.patch(
        "app.celery.messagebox_scheduled_tasks.parse_berichten_verwerk_response",
        return_value=_batch(
            total_received=1,
            successful_count=1,
            messages=[ParsedBericht(message_id="notif-1", process_code="00", bericht_type="bericht", stadium="NA")],
        ),
    )
    mocker.patch(
        "app.celery.messagebox_scheduled_tasks.process_messagebox_client_response.apply_async",
        side_effect=Exception("broker down"),
    )

    messagebox_process_unprocessed_messages()

    mock_core_client.process_message.assert_not_called()


def test_messagebox_process_unprocessed_messages_no_unprocessed(mocker):
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsAdapterClientConfig")
    mock_core_client = mocker.Mock()
    mock_core_client.__enter__ = mocker.Mock(return_value=mock_core_client)
    mock_core_client.__exit__ = mocker.Mock(return_value=False)
    mock_core_client.list_unprocessed_message_ids.return_value = []
    mocker.patch("app.celery.messagebox_scheduled_tasks.EbmsCoreClient", return_value=mock_core_client)

    messagebox_process_unprocessed_messages()

    mock_core_client.get_message.assert_not_called()


def test_check_if_messagebox_still_pending_redispatches_created(mocker, messagebox_notification):
    messagebox_notification.status = NOTIFICATION_CREATED
    messagebox_notification.created_at = datetime.utcnow() - timedelta(minutes=120)
    # fixture defaults to status=sending, which sets updated_at=now on creation --
    # backdate it too so this reflects a notification untouched since creation
    # (the query now uses COALESCE(updated_at, created_at) to tell an actively
    # retrying notification apart from a genuinely stuck one).
    messagebox_notification.updated_at = messagebox_notification.created_at
    mock_send_task = mocker.patch("app.celery.messagebox_scheduled_tasks.notify_celery.send_task")

    check_if_messagebox_still_pending(max_minutes_ago_to_check=60)

    mock_send_task.assert_called_once_with(
        name=TaskNamesNL.MESSAGEBOX_DELIVER,
        kwargs={"notification_id": str(messagebox_notification.id)},
        queue=QueueNamesNL.MESSAGEBOX,
    )


def test_check_if_messagebox_still_pending_never_resends_sending(mocker, messagebox_notification):
    # messagebox_notification fixture defaults to NOTIFICATION_SENDING -- ebms-core
    # already accepted it, so a stuck one must never be blindly resent (it would be
    # rejected as a duplicate BerichtID and race the real async result).
    messagebox_notification.created_at = datetime.utcnow() - timedelta(minutes=120)
    mock_send_task = mocker.patch("app.celery.messagebox_scheduled_tasks.notify_celery.send_task")

    check_if_messagebox_still_pending(max_minutes_ago_to_check=60, max_hours_ago_to_check_sending=24)

    mock_send_task.assert_not_called()


def test_check_if_messagebox_still_pending_alerts_zendesk_for_stuck_sending(mocker, messagebox_notification):
    # messagebox_notification fixture defaults to NOTIFICATION_SENDING.
    messagebox_notification.created_at = datetime.utcnow() - timedelta(hours=48)
    messagebox_scheduled_tasks.current_app.config["SEND_ZENDESK_ALERTS_ENABLED"] = True
    mock_zendesk = mocker.patch("app.celery.messagebox_scheduled_tasks.zendesk_client.send_ticket_to_zendesk")

    check_if_messagebox_still_pending(max_hours_ago_to_check_sending=24)

    mock_zendesk.assert_called_once()


def test_check_if_messagebox_still_pending_ignores_recently_sending(mocker, messagebox_notification):
    # messagebox_notification fixture defaults to NOTIFICATION_SENDING.
    messagebox_notification.created_at = datetime.utcnow()
    mock_zendesk = mocker.patch("app.celery.messagebox_scheduled_tasks.zendesk_client.send_ticket_to_zendesk")

    check_if_messagebox_still_pending(max_hours_ago_to_check_sending=24)

    mock_zendesk.assert_not_called()


def test_check_if_messagebox_still_pending_alerts_zendesk_for_stuck_virus_check(mocker, messagebox_notification):
    messagebox_notification.status = NOTIFICATION_PENDING_VIRUS_CHECK
    messagebox_notification.created_at = datetime.utcnow() - timedelta(minutes=120)
    # fixture defaults to status=sending, which sets updated_at=now on creation --
    # backdate it too so this reflects a notification untouched since creation
    # (the query now uses COALESCE(updated_at, created_at) to tell an actively
    # retrying notification apart from a genuinely stuck one).
    messagebox_notification.updated_at = messagebox_notification.created_at
    messagebox_scheduled_tasks.current_app.config["SEND_ZENDESK_ALERTS_ENABLED"] = True
    mock_zendesk = mocker.patch("app.celery.messagebox_scheduled_tasks.zendesk_client.send_ticket_to_zendesk")

    check_if_messagebox_still_pending(max_minutes_ago_to_check=60)

    mock_zendesk.assert_called_once()


def test_check_if_messagebox_still_pending_ignores_recent_notifications(mocker, messagebox_notification):
    messagebox_notification.status = NOTIFICATION_CREATED
    messagebox_notification.created_at = datetime.utcnow()
    mock_send_task = mocker.patch("app.celery.messagebox_scheduled_tasks.notify_celery.send_task")

    check_if_messagebox_still_pending(max_minutes_ago_to_check=60)

    mock_send_task.assert_not_called()


def test_check_if_messagebox_still_pending_ignores_actively_retrying_created(mocker, messagebox_notification):
    # messagebox_deliver touches updated_at on every retry attempt while it cycles
    # through its own bounded retries (up to 4h: 48 x 300s), so a notification with
    # an old created_at but a recent updated_at is still within its own retry budget
    # and must not get a duplicate messagebox_deliver dispatched on top of it.
    messagebox_notification.status = NOTIFICATION_CREATED
    messagebox_notification.created_at = datetime.utcnow() - timedelta(minutes=120)
    messagebox_notification.updated_at = datetime.utcnow() - timedelta(minutes=5)
    mock_send_task = mocker.patch("app.celery.messagebox_scheduled_tasks.notify_celery.send_task")

    check_if_messagebox_still_pending(max_minutes_ago_to_check=60)

    mock_send_task.assert_not_called()
