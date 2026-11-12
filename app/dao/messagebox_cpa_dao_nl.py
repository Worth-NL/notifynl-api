from datetime import datetime

from app import db
from app.dao.dao_utils import autocommit
from app.models_nl import MessageboxCpaSelection, MessageboxCpaSelectionHistory


def dao_get_messagebox_cpa_selection(purpose: str) -> MessageboxCpaSelection | None:
    return db.session.get(MessageboxCpaSelection, purpose)


def dao_get_messagebox_cpa_selections() -> list[MessageboxCpaSelection]:
    return MessageboxCpaSelection.query.order_by(MessageboxCpaSelection.purpose).all()


@autocommit
def dao_set_messagebox_cpa_selection(
    purpose: str,
    *,
    cpa_id: str,
    from_party_id: str,
    to_party_id: str,
    action: str,
    message_type: str,
    updated_by_id,
) -> MessageboxCpaSelection:
    """Selects a CPA for a purpose and records it in the history, in one transaction."""
    selection = dao_get_messagebox_cpa_selection(purpose) or MessageboxCpaSelection(purpose=purpose)
    selection.cpa_id = cpa_id
    selection.from_party_id = from_party_id
    selection.to_party_id = to_party_id
    selection.action = action
    selection.message_type = message_type
    selection.updated_by_id = updated_by_id
    selection.updated_at = datetime.utcnow()
    db.session.add(selection)
    db.session.add(MessageboxCpaSelectionHistory.from_original(selection))
    return selection


def dao_get_messagebox_cpa_selection_history(purpose: str) -> list[MessageboxCpaSelectionHistory]:
    return (
        MessageboxCpaSelectionHistory.query.filter_by(purpose=purpose)
        .order_by(MessageboxCpaSelectionHistory.updated_at.desc())
        .all()
    )
