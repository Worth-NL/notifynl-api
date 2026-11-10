import logging

import sentry_sdk
from ebms_adapter_client import EbmsAdapterClientConfig
from ebms_adapter_client.berichtenbox import (
    BerichtenboxAttachment,
    BerichtenboxContractConfig,
    build_berichten_xml,
    build_message_request,
)
from ebms_adapter_client.client import EbmsAdapterClient as EbmsCoreClient
from ebms_adapter_client.exceptions import BerichtenboxValidationError, EbmsAdapterError, EbmsBadRequestError

from app.clients.messagebox import MessageboxClient, MessageboxClientException, MessageboxClientNonRetryableException
from app.otel_metrics.provider import record_request_duration

logger = logging.getLogger(__name__)

# VerwerkingsCode values only (see Logius's "Technische Aansluithandleiding
# MijnOverheid Berichtenbox", section 5.6) -- a real success always carries
# VerwerkingsCode=Verwerkt, never "0". Stadium (the processing phase a
# failure was detected in, e.g. ValidatieBerichtType/ValidatieGebruiker/
# StoreMessage) is a separate field on the response and must not be
# confused with VerwerkingsCode -- it's threaded through separately, see
# process_messagebox_client_response's `stadium` parameter.
messagebox_response_map = {
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


def get_messagebox_failure_reason(detailed_status_code):
    """Decodes a Logius VerwerkingsCode into its Dutch human-readable reason
    text, regardless of which top-level status it's nested under in
    ``messagebox_response_map``. Returns ``None`` for an unrecognized or
    absent code."""
    if not detailed_status_code:
        return None
    for entry in messagebox_response_map.values():
        reason = entry["reasoncode"].get(detailed_status_code)
        if reason:
            return reason
    return None


class EbmsAdapterClient(MessageboxClient):
    """
    EbMS Adapter messagebox client.

    This class is not thread-safe
    """

    name = "ebms-adapter"

    def __init__(self, current_app):
        super().__init__(current_app)

        self.url = self.current_app.config.get("EBMS_ADAPTER_URL")
        # The CPA isn't fixed here: each send looks up the one for its key type (app/messagebox/contract_nl.py).

    @record_request_duration(notification_type="messagebox", provider_name="ebms-adapter")
    def try_send_messagebox(self, notification_id: str) -> str:
        """Sends a messagebox notification to the ebms-adapter. Returns the
        ebms-core envelope message_id."""
        # Deferred imports: this module is imported by app/__init__.py before
        # `db`/`encryption` are defined on the `app` package, so importing
        # anything that pulls in app.models/app.dao at module level would
        # cause a circular import (mirrors the pattern in app/clients/letter/dvla.py).
        from app import encryption
        from app.dao import notifications_dao
        from app.messagebox.contract_nl import get_send_contract
        from app.messagebox.utils import get_messagebox_attachments

        notification = notifications_dao.get_notification_by_id(notification_id, _raise=True)
        service = notification.service
        bsn = encryption.decrypt(notification.to)
        personalisation = notification.personalisation or {}
        attachments = get_messagebox_attachments(notification)

        # ebms-adapter-client treats batch_id/bericht_id as independent, generic ebms
        # concepts -- NotifyNL specifically chooses to reuse the same value for both here,
        # since messagebox_deliver always sends exactly one notification per batch. Logius
        # echoes BatchID back verbatim even when it can't determine BerichtID (e.g. XSD
        # validation failure), so this gives messagebox_scheduled_tasks a reliable
        # correlation fallback with no persistence needed.
        notification_id = str(notification.id)

        contract = get_send_contract(notification.key_type)
        if contract is None:
            # A team key without a `team` CPA selection: it must never fall back to the live CPA, which would send
            # a test message to a real citizen. The API refuses these up front; this covers a selection removed since.
            raise MessageboxClientNonRetryableException(
                f"No messagebox CPA selected for {notification.key_type} key notification {notification_id}"
            )
        sentry_sdk.set_tag("ebms_cpa_purpose", contract.purpose)
        logger.info(
            "Sending messagebox notification %s under CPA %s (%s)",
            notification_id,
            contract.cpa_id,
            contract.purpose,
            extra={
                "notification_id": notification_id,
                "ebms_cpa_purpose": contract.purpose,
                "ebms_cpa_id": contract.cpa_id,
                "ebms_cpa_from_config": contract.from_config,
            },
        )

        config = EbmsAdapterClientConfig(base_url=self.url)
        try:
            xml_content = build_berichten_xml(
                batch_id=notification_id,
                bericht_id=notification_id,
                bsn=bsn,
                message=personalisation.get("message", ""),
                subject=personalisation.get("subject", "Berichtenboxbericht"),
                deliverer_id=service.oin,
                message_type=personalisation.get("message_type") or contract.message_type,
                attachments=[
                    BerichtenboxAttachment(filename=attachment["filename"], content=attachment["content"])
                    for attachment in attachments
                ],
            )

            message_request = build_message_request(
                contract=BerichtenboxContractConfig(cpa_id=contract.cpa_id, action=contract.action),
                from_party_id=contract.from_party_id,
                to_party_id=contract.to_party_id,
                bericht_id=notification_id,
                xml_content=xml_content,
            )

            with EbmsCoreClient(config) as core_client:
                return core_client.send_message(message_request)
        except BerichtenboxValidationError as e:
            # Building the XML itself failed a documented Berichtenbox constraint --
            # no HTTP call was ever made, and retrying with the same input can never
            # succeed, so this must be treated the same as a non-retryable rejection.
            raise MessageboxClientNonRetryableException(str(e)) from e
        except EbmsBadRequestError as e:
            raise MessageboxClientNonRetryableException(str(e)) from e
        except EbmsAdapterError as e:
            raise MessageboxClientException(str(e)) from e
