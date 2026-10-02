import pytest

from app.dao.organisation_dao import dao_get_organisation_domains
from app.dao.users_dao import is_gov_user, user_can_be_archived, user_can_be_removed_from_service
from tests.app.db import create_organisation, create_permissions, create_user


@pytest.mark.parametrize(
    "email_address, expected",
    [
        ("user@amsterdam.nl", True),  # on the Dutch government domain list
        ("user@denhaag.nl", True),
        ("user@other.com", True),  # linked to an organisation
        ("user@gov.uk", False),  # UK government domains don't count for NotifyNL
        ("user@example.com", False),
    ],
)
def test_is_gov_user_nl(notify_db_session, email_address, expected):
    create_organisation(domains=["other.com"])

    assert is_gov_user(email_address, dao_get_organisation_domains()) is expected


def test_user_cannot_be_archived_if_there_are_not_enough_dutch_gov_users(sample_service, notify_db_session):
    gov_user = create_user(email="1@amsterdam.nl")
    non_gov_user = create_user(email="2@example.com")
    another_non_gov_user = create_user(email="3@gov.uk")

    sample_service.users = [gov_user, non_gov_user, another_non_gov_user]
    for user in sample_service.users:
        create_permissions(user, sample_service, "manage_settings")
    notify_db_session.commit()

    assert not user_can_be_archived(gov_user)


def test_user_can_be_archived_if_enough_dutch_gov_users_remain(sample_service, notify_db_session):
    user_to_archive = create_user(email="1@amsterdam.nl")
    sample_service.users = [user_to_archive, create_user(email="2@denhaag.nl"), create_user(email="3@utrecht.nl")]
    for user in sample_service.users:
        create_permissions(user, sample_service, "manage_settings")
    notify_db_session.commit()

    assert user_can_be_archived(user_to_archive)


def test_uk_gov_user_with_manage_settings_can_always_be_removed(sample_service, notify_db_session):
    uk_user = create_user(email="1@gov.uk")
    sample_service.users = [uk_user, create_user(email="2@amsterdam.nl")]
    for user in sample_service.users:
        create_permissions(user, sample_service, "manage_settings")
    notify_db_session.commit()

    assert user_can_be_removed_from_service(uk_user, sample_service)
