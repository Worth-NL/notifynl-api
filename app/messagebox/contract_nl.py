"""Which CPA a messagebox notification is sent under, looked up per send from the platform-admin selection."""

from dataclasses import dataclass

from flask import current_app

from app.constants import KEY_TYPE_TEAM
from app.dao.messagebox_cpa_dao_nl import dao_get_messagebox_cpa_selection
from app.messagebox.constants import CPA_PURPOSE_LIVE, CPA_PURPOSE_TEAM

DEFAULT_ACTION = "GLOBE-R-BV-Request"
DEFAULT_MESSAGE_TYPE = "bericht"


@dataclass(frozen=True)
class SendContract:
    purpose: str
    cpa_id: str
    action: str
    from_party_id: str
    to_party_id: str
    message_type: str
    # whether this came from the EBMS_BERICHTENBOX_* config rather than a platform-admin selection
    from_config: bool = False


def purpose_for_key_type(key_type: str) -> str:
    return CPA_PURPOSE_TEAM if key_type == KEY_TYPE_TEAM else CPA_PURPOSE_LIVE


def _from_config() -> SendContract | None:
    config = current_app.config
    cpa_id = config.get("EBMS_BERICHTENBOX_CPA_ID")
    from_party_id = config.get("EBMS_BERICHTENBOX_FROM_PARTY_ID")
    to_party_id = config.get("EBMS_BERICHTENBOX_TO_PARTY_ID")
    if not (cpa_id and from_party_id and to_party_id):
        return None
    return SendContract(
        purpose=CPA_PURPOSE_LIVE,
        cpa_id=cpa_id,
        action=config.get("EBMS_BERICHTENBOX_ACTION") or DEFAULT_ACTION,
        from_party_id=f"urn:osb:oin:{from_party_id}",
        to_party_id=f"urn:osb:oin:{to_party_id}",
        message_type=config.get("EBMS_BERICHTENBOX_MESSAGE_TYPE") or DEFAULT_MESSAGE_TYPE,
        from_config=True,
    )


def get_send_contract(key_type: str) -> SendContract | None:
    """
    The CPA for a notification sent with this key type, or None when there is none to send under. Team keys use only
    the platform-admin `team` selection and never fall back to the live CPA; normal keys use the `live` selection, or
    the EBMS_BERICHTENBOX_* config until one is made.
    """
    purpose = purpose_for_key_type(key_type)
    selection = dao_get_messagebox_cpa_selection(purpose)
    if selection is not None:
        return SendContract(
            purpose=purpose,
            cpa_id=selection.cpa_id,
            action=selection.action,
            from_party_id=selection.from_party_id,
            to_party_id=selection.to_party_id,
            message_type=selection.message_type,
        )
    if purpose == CPA_PURPOSE_LIVE:
        return _from_config()
    return None
