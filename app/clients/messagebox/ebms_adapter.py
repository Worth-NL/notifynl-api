import logging
import uuid

from ebms_adapter_client import EbmsAdapterClientConfig
from ebms_adapter_client.berichtenbox import (
    BerichtenboxAttachment,
    BerichtenboxContractConfig,
    build_berichten_xml,
    build_message_request,
)
from ebms_adapter_client.client import EbmsAdapterClient as EbmsCoreClient
from ebms_adapter_client.exceptions import EbmsAdapterError, EbmsBadRequestError

from app.clients.messagebox import MessageboxClient, MessageboxClientException, MessageboxClientNonRetryableException

logger = logging.getLogger(__name__)


class EbmsAdapterClient(MessageboxClient):
    """
    EbMS Adapter messagebox client.

    This class is not thread-safe
    """

    name = "ebms-adapter"

    def __init__(self, current_app, statsd_client):
        super().__init__(current_app, statsd_client)

        self.url = self.current_app.config.get("EBMS_ADAPTER_URL")
        self._contract = BerichtenboxContractConfig(
            cpa_id=self.current_app.config["EBMS_BERICHTENBOX_CPA_ID"],
            action=self.current_app.config.get("EBMS_BERICHTENBOX_ACTION", "GLOBE-R-BV-Request"),
        )

    def try_send_messagebox(self, notification_id: str) -> str:
        """Sends a messagebox notification to the ebms-adapter. Returns the
        ebms-core envelope message_id."""
        # Deferred imports: this module is imported by app/__init__.py before
        # `db`/`signing` are defined on the `app` package, so importing
        # anything that pulls in app.models/app.dao at module level would
        # cause a circular import (mirrors the pattern in app/clients/letter/dvla.py).
        from app import signing
        from app.dao import notifications_dao
        from app.messagebox.utils import get_messagebox_attachments

        notification = notifications_dao.get_notification_by_id(notification_id, _raise=True)
        service = notification.service
        bsn = signing.decode(notification.to)
        personalisation = notification.personalisation or {}
        attachments = get_messagebox_attachments(notification)

        xml_content = build_berichten_xml(
            batch_id=str(uuid.uuid4()),
            notification_id=str(notification.id),
            bsn=bsn,
            message=personalisation.get("message", ""),
            subject=personalisation.get("subject", "Berichtenboxbericht"),
            deliverer_id=service.oin,
            attachments=[
                BerichtenboxAttachment(filename=attachment["filename"], content=attachment["content"])
                for attachment in attachments
            ],
        )

        message_request = build_message_request(
            contract=self._contract,
            from_party_id=f"urn:osb:oin:{self.current_app.config['EBMS_BERICHTENBOX_FROM_PARTY_ID']}",
            to_party_id=f"urn:osb:oin:{self.current_app.config['EBMS_BERICHTENBOX_TO_PARTY_ID']}",
            notification_id=str(notification.id),
            xml_content=xml_content,
        )

        config = EbmsAdapterClientConfig(base_url=self.url)
        try:
            with EbmsCoreClient(config) as core_client:
                return core_client.send_message(message_request)
        except EbmsBadRequestError as e:
            raise MessageboxClientNonRetryableException(str(e)) from e
        except EbmsAdapterError as e:
            raise MessageboxClientException(str(e)) from e
