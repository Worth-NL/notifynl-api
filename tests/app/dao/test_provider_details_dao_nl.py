from app.constants import LETTER_TYPE
from app.dao.provider_details_dao import get_provider_details_by_notification_type


def test_dvla_stays_the_first_letter_provider_by_priority(notify_db_session):
    # the legacy DVLA delivery path takes the first letter provider by priority as `sent_by`
    providers = get_provider_details_by_notification_type(LETTER_TYPE)

    assert [provider.identifier for provider in providers] == ["dvla", "pingen", "rest-endpoint"]
