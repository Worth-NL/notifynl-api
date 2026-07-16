import logging
import uuid
from datetime import datetime

from flask import current_app

from app import notify_celery, statsd_client
from app.clients import ClientException
from app.config import TaskNamesNL
from app.constants import NOTIFICATION_PENDING
from app.dao import notifications_dao
from app.notifications.notifications_ses_callback import (
    check_and_queue_callback_task,
)


@notify_celery.task(
    bind=True,
    name=TaskNamesNL.MESSAGEBOX_PROCESS_CALLBACKS,
    max_retries=5,
    default_retry_delay=300,
    early_log_level=logging.DEBUG,
)
def process_messagebox_client_response(
    self, status, provider_reference, client_name, detailed_status_code=None, stadium=None
):
    # validate reference
    try:
        uuid.UUID(provider_reference, version=4)
    except ValueError as e:
        current_app.logger.exception("%s callback with invalid reference %s", client_name, provider_reference)
        raise e

    response_parser = get_messagebox_responses

    # validate status
    try:
        notification_status, detailed_status = response_parser(status, detailed_status_code)
        current_app.logger.info(
            "%s callback returned status of %s(%s): %s(%s) stadium=%s for reference: %s",
            client_name,
            notification_status,
            status,
            detailed_status,
            detailed_status_code,
            stadium,
            provider_reference,
        )
    except KeyError as e:
        _process_for_status(
            notification_status="technical-failure", client_name=client_name, provider_reference=provider_reference
        )
        raise ClientException(f"{client_name} callback failed: status {status} not found.") from e

    _process_for_status(
        notification_status=notification_status,
        client_name=client_name,
        provider_reference=provider_reference,
        detailed_status_code=detailed_status_code,
        stadium=stadium,
    )


def _process_for_status(notification_status, client_name, provider_reference, detailed_status_code=None, stadium=None):
    # record stats
    notification = notifications_dao.update_notification_status_by_id(
        notification_id=provider_reference,
        status=notification_status,
        detailed_status_code=detailed_status_code,
        messagebox_stadium=stadium,
    )
    if not notification:
        return

    statsd_client.incr(f"callback.{client_name.lower()}.{notification_status}")

    if notification.sent_at:
        statsd_client.timing_with_dates(
            f"callback.{client_name.lower()}.{notification_status}.elapsed-time",
            datetime.utcnow(),
            notification.sent_at,
        )

    if notification_status != NOTIFICATION_PENDING:
        check_and_queue_callback_task(notification)


messagebox_response_map = {
    # VerwerkingsCode values only (see Logius's "Technische Aansluithandleiding
    # MijnOverheid Berichtenbox", section 5.6) -- a real success always carries
    # VerwerkingsCode=Verwerkt, never "0". Stadium (the processing phase a
    # failure was detected in, e.g. ValidatieBerichtType/ValidatieGebruiker/
    # StoreMessage) is a separate field on the response and must not be
    # confused with VerwerkingsCode -- it's threaded through separately, see
    # process_messagebox_client_response's `stadium` parameter.
    "10": {"status": "delivered", "reasoncode": {"Verwerkt": "No error"}},
    "20": {
        "status": "permanent-failure",
        "reasoncode": {
            "TechnischProbleem": "Technisch probleem bij verwerken",
            "NietActiefOfGeabonneerd": "Geen actieve berichtenbox of geen abonnement",
            "BerichtTypeNietOndersteund": "Bericht type bestaat niet of is niet actief",
            "AanmaakDatumLigtTeVerInHetVerleden": "Aanmaakdatum te ver in het verleden",
            "PublicatieDatumLigtTeVerInDeToekomst": "Publicatiedatum te ver in de toekomst",
            "BerichtBestaatAl": "Een bericht met hetzelfde berichtID is reeds aangeboden",
            "BijlageTeGroot": "De omvang van de persoonlijke bijlage(n) in het bericht is te groot",
            "OinInCPAKomtNietOvereenMetOinInBericht": "OIN uit CPA komt niet overeen met OID in het bericht",
            "XmlValidatieTegenXsdValtNegatiefUit": "Bericht xml valideert niet tegen XSD",
        },
    },
}


def get_messagebox_responses(status, detailed_status_code=None):
    return (
        messagebox_response_map[status]["status"],
        messagebox_response_map[status]["reasoncode"].get(detailed_status_code, None),
    )
