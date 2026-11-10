from datetime import UTC, datetime

import pytest
from ebms_adapter_client import EbmsBadRequestError, EbmsServerError
from flask import current_app

from app.messagebox import cpa_nl
from app.messagebox.constants import CPA_PURPOSE_LIVE, CPA_PURPOSE_TEAM
from app.models_nl import MessageboxCpaSelection, MessageboxCpaSelectionHistory
from tests.app.db_nl import create_messagebox_cpa_selection
from tests.app.messagebox.cpa_xml_nl import (
    LIVE_ENDPOINT,
    LOGIUS_OIN,
    OWN_ENDPOINT,
    OWN_OIN,
    PREPROD_ENDPOINT,
    make_cpa_xml,
)
from tests.conftest import set_config_values

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def cpa_config(notify_api, mocker):
    # patch.dict, not set_config_values: it removes keys the "test" config doesn't have once the test is done
    mocker.patch.dict(
        current_app.config,
        {
            "EBMS_PUBLIC_ENDPOINT": OWN_ENDPOINT,
            "EBMS_LIVE_ENDPOINT_HOSTS": ("globe-ebms-internet.procesinfrastructuur.nl",),
            "EBMS_PREPROD_ENDPOINT_HOSTS": ("preprod-globe-ebms-*.procesinfrastructuur.nl",),
            "EBMS_BERICHTENBOX_ACTION": "GLOBE-R-BV-Request",
            "EBMS_ADAPTER_URL": "http://ebms-core.invalid",
        },
    )


@pytest.fixture
def core_client(mocker):
    client = mocker.Mock()
    client.__enter__ = mocker.Mock(return_value=client)
    client.__exit__ = mocker.Mock(return_value=False)
    client.list_cpa_ids.return_value = []
    mocker.patch("app.messagebox.cpa_nl.EbmsCoreClient", return_value=client)
    return client


def _failed_checks(assessment):
    return [check.name for check in assessment.checks if not check.passed]


def test_validate_accepts_a_preprod_cpa_for_team(core_client):
    cpa_xml = make_cpa_xml()

    assessment = cpa_nl.validate(cpa_xml, CPA_PURPOSE_TEAM)

    assert assessment.eligible
    assert [check.name for check in assessment.checks] == [
        cpa_nl.CHECK_EBMS_CORE,
        cpa_nl.CHECK_PARTIES,
        cpa_nl.CHECK_OWN_ENDPOINT,
        cpa_nl.CHECK_COUNTERPARTY_ENDPOINT,
        cpa_nl.CHECK_ACTION,
        cpa_nl.CHECK_STATUS,
        cpa_nl.CHECK_PERIOD,
    ]
    core_client.validate_cpa.assert_called_once_with(cpa_xml)
    core_client.insert_cpa.assert_not_called()


def test_validate_accepts_a_production_cpa_for_live(core_client):
    assert cpa_nl.validate(make_cpa_xml(logius_endpoint=LIVE_ENDPOINT), CPA_PURPOSE_LIVE).eligible


@pytest.mark.parametrize(
    ("purpose", "cpa_kwargs", "failed_check"),
    [
        (CPA_PURPOSE_LIVE, {"logius_endpoint": PREPROD_ENDPOINT}, cpa_nl.CHECK_COUNTERPARTY_ENDPOINT),
        (CPA_PURPOSE_TEAM, {"logius_endpoint": LIVE_ENDPOINT}, cpa_nl.CHECK_COUNTERPARTY_ENDPOINT),
        (
            CPA_PURPOSE_TEAM,
            {"logius_endpoint": "https://ebms.attacker.example/ebXML"},
            cpa_nl.CHECK_COUNTERPARTY_ENDPOINT,
        ),
        (
            CPA_PURPOSE_TEAM,
            {"logius_endpoint": "https://preprod-globe-ebms-x.attacker.example/ebXML"},
            cpa_nl.CHECK_COUNTERPARTY_ENDPOINT,
        ),
        (
            CPA_PURPOSE_TEAM,
            {"logius_endpoint": "https://preprod-globe-ebms-x.attacker.example.procesinfrastructuur.nl/ebXML"},
            cpa_nl.CHECK_COUNTERPARTY_ENDPOINT,
        ),
        (CPA_PURPOSE_TEAM, {"own_endpoint": "https://ebms.other-environment.invalid/ebms"}, cpa_nl.CHECK_OWN_ENDPOINT),
        (CPA_PURPOSE_TEAM, {"own_actions": ("GLOBE-R-A-Request",)}, cpa_nl.CHECK_ACTION),
        (CPA_PURPOSE_TEAM, {"process": "MijnOverheid_BB"}, cpa_nl.CHECK_ACTION),
        (CPA_PURPOSE_TEAM, {"own_role": "SP", "logius_role": "SR"}, cpa_nl.CHECK_ACTION),
        (CPA_PURPOSE_TEAM, {"logius_role": "Provider"}, cpa_nl.CHECK_ACTION),
        (CPA_PURPOSE_TEAM, {"logius_receives": ("GLOBE-R-A-Request",)}, cpa_nl.CHECK_ACTION),
        (
            CPA_PURPOSE_TEAM,
            {"logius_endpoint": "http://preprod-globe-ebms-internet.procesinfrastructuur.nl/ebXML"},
            cpa_nl.CHECK_COUNTERPARTY_ENDPOINT,
        ),
        (
            CPA_PURPOSE_TEAM,
            {"start": "2027-01-01T00:00:00Z", "end": "2027-01-01T00:00:00Z"},
            cpa_nl.CHECK_PERIOD,
        ),
        (CPA_PURPOSE_TEAM, {"end": "2026-11-01T00:00:00Z"}, cpa_nl.CHECK_PERIOD),
        (CPA_PURPOSE_TEAM, {"start": "2026-12-01T00:00:00Z"}, cpa_nl.CHECK_PERIOD),
        (CPA_PURPOSE_TEAM, {"end": "2026-11-10T12:00:00Z"}, cpa_nl.CHECK_PERIOD),
        (CPA_PURPOSE_TEAM, {"status": "proposed"}, cpa_nl.CHECK_STATUS),
    ],
    ids=[
        "preprod-host-for-live",
        "prod-host-for-team",
        "host-not-allowlisted",
        "lookalike-host",
        "wildcard-spans-labels",
        "wrong-own-endpoint",
        "cannot-send-action",
        "wrong-process",
        "roles-swapped",
        "other-receiver-role",
        "receiver-cannot-receive-action",
        "cleartext-endpoint",
        "start-not-before-end",
        "expired",
        "not-started",
        "ends-now",
        "proposed",
    ],
)
def test_assess_rejects(purpose, cpa_kwargs, failed_check):
    summary = cpa_nl.parse_cpa_summary(make_cpa_xml(**cpa_kwargs))

    assessment = cpa_nl.assess(summary, purpose, now=NOW)

    assert not assessment.eligible
    assert failed_check in _failed_checks(assessment)


def test_assess_rejects_every_cpa_without_a_public_endpoint():
    summary = cpa_nl.parse_cpa_summary(make_cpa_xml())

    with set_config_values(current_app, {"EBMS_PUBLIC_ENDPOINT": ""}):
        assessment = cpa_nl.assess(summary, CPA_PURPOSE_TEAM, now=NOW)

    assert cpa_nl.CHECK_OWN_ENDPOINT in _failed_checks(assessment)
    # without our own party, the other party and the action can't be checked either
    assert cpa_nl.CHECK_COUNTERPARTY_ENDPOINT in _failed_checks(assessment)
    assert cpa_nl.CHECK_ACTION in _failed_checks(assessment)


def test_assess_allows_a_trailing_slash_and_case_difference_in_our_endpoint():
    summary = cpa_nl.parse_cpa_summary(make_cpa_xml(own_endpoint="https://EBMS.example.invalid/ebms/"))

    assert cpa_nl.assess(summary, CPA_PURPOSE_TEAM, now=NOW).eligible


def test_assess_warns_when_the_cpa_ends_within_60_days():
    summary = cpa_nl.parse_cpa_summary(make_cpa_xml(end="2026-12-31T00:00:00Z"))

    assessment = cpa_nl.assess(summary, CPA_PURPOSE_TEAM, now=NOW)

    assert assessment.eligible
    assert assessment.warnings == ("The CPA ends on 2026-12-31",)


def test_validate_reports_ebms_core_rejection(core_client):
    core_client.validate_cpa.side_effect = EbmsBadRequestError("invalid CPA", status_code=400)

    assessment = cpa_nl.validate(make_cpa_xml(), CPA_PURPOSE_TEAM)

    assert _failed_checks(assessment) == [cpa_nl.CHECK_EBMS_CORE]


def test_validate_reports_a_refusal_ebms_core_answers_with_500(core_client):
    # ebms-core 2.20.2's CPAValidator refusals come back as 500 with the reason in the body
    core_client.validate_cpa.side_effect = EbmsServerError("CPA version 1.0 not supported!", status_code=500)

    assessment = cpa_nl.validate(make_cpa_xml(), CPA_PURPOSE_TEAM)

    assert _failed_checks(assessment) == [cpa_nl.CHECK_EBMS_CORE]
    assert "CPA version 1.0 not supported!" in assessment.checks[0].message


@pytest.mark.parametrize(
    "cpa_kwargs",
    [{"status": "proposed"}, {"end": "2026-01-02T00:00:00Z"}, {"logius_endpoint": LIVE_ENDPOINT}],
    ids=["proposed", "expired", "host-not-allowed"],
)
def test_validate_skips_ebms_core_for_a_cpa_the_guardrails_refuse(core_client, cpa_kwargs):
    assessment = cpa_nl.validate(make_cpa_xml(**cpa_kwargs), CPA_PURPOSE_TEAM)

    assert not assessment.eligible
    assert cpa_nl.CHECK_EBMS_CORE not in [check.name for check in assessment.checks]
    core_client.validate_cpa.assert_not_called()


def test_send_roles_match_the_send_contract():
    # the send path builds BerichtenboxContractConfig without roles, so the CPA must bind its defaults
    assert (cpa_nl.SENDER_ROLE, cpa_nl.RECEIVER_ROLE) == ("SR", "SP")


def test_validate_rejects_xml_that_is_not_a_cpa(core_client):
    with pytest.raises(cpa_nl.CpaRejected, match="Expected a CollaborationProtocolAgreement"):
        cpa_nl.validate("<Something/>", CPA_PURPOSE_TEAM)

    core_client.validate_cpa.assert_not_called()


def test_upload_inserts_an_eligible_cpa_without_overwriting(core_client):
    cpa_xml = make_cpa_xml()

    cpa_nl.upload(cpa_xml, CPA_PURPOSE_TEAM)

    core_client.insert_cpa.assert_called_once_with(cpa_xml, overwrite=False)


def test_upload_refuses_an_ineligible_cpa(core_client):
    with pytest.raises(cpa_nl.CpaRejected) as error:
        cpa_nl.upload(make_cpa_xml(logius_endpoint=LIVE_ENDPOINT), CPA_PURPOSE_TEAM)

    assert not error.value.assessment.eligible
    core_client.validate_cpa.assert_not_called()
    core_client.insert_cpa.assert_not_called()


def test_upload_refuses_a_cpa_id_ebms_core_already_has(core_client):
    core_client.list_cpa_ids.return_value = ["EXAMPLE-EBMS-BB-2-0_0001"]

    with pytest.raises(cpa_nl.CpaRejected, match="already has a CPA with id EXAMPLE-EBMS-BB-2-0_0001"):
        cpa_nl.upload(make_cpa_xml(), CPA_PURPOSE_TEAM)

    core_client.insert_cpa.assert_not_called()


def test_select_stores_the_parties_from_the_cpa_and_writes_history(core_client, notify_user):
    core_client.list_cpa_ids.return_value = ["EXAMPLE-EBMS-BB-2-0_0001"]
    core_client.get_cpa.return_value = make_cpa_xml()

    selection = cpa_nl.select(
        CPA_PURPOSE_TEAM, "EXAMPLE-EBMS-BB-2-0_0001", message_type="test-bericht", user_id=notify_user.id
    )

    assert selection.purpose == CPA_PURPOSE_TEAM
    assert selection.cpa_id == "EXAMPLE-EBMS-BB-2-0_0001"
    assert selection.from_party_id == f"urn:osb:oin:{OWN_OIN}"
    assert selection.to_party_id == f"urn:osb:oin:{LOGIUS_OIN}"
    assert selection.action == "GLOBE-R-BV-Request"
    assert selection.message_type == "test-bericht"
    assert selection.updated_by_id == notify_user.id
    (history,) = MessageboxCpaSelectionHistory.query.all()
    assert (history.purpose, history.cpa_id, history.updated_by_id) == (
        CPA_PURPOSE_TEAM,
        "EXAMPLE-EBMS-BB-2-0_0001",
        notify_user.id,
    )
    core_client.validate_cpa.assert_called_once()


def test_select_replaces_an_earlier_selection_and_records_the_new_one(core_client, notify_user):
    create_messagebox_cpa_selection(CPA_PURPOSE_TEAM, updated_by=notify_user, cpa_id="OLD")
    core_client.list_cpa_ids.return_value = ["NEW"]
    core_client.get_cpa.return_value = make_cpa_xml(cpa_id="NEW")

    cpa_nl.select(CPA_PURPOSE_TEAM, "NEW", message_type="test-bericht", user_id=notify_user.id)

    assert MessageboxCpaSelection.query.one().cpa_id == "NEW"
    assert [entry.cpa_id for entry in MessageboxCpaSelectionHistory.query.all()] == ["NEW"]


def test_select_refuses_a_cpa_ebms_core_does_not_have(core_client, notify_user):
    with pytest.raises(cpa_nl.CpaRejected, match="ebms-core has no CPA with id MISSING"):
        cpa_nl.select(CPA_PURPOSE_TEAM, "MISSING", message_type="test-bericht", user_id=notify_user.id)

    assert MessageboxCpaSelection.query.count() == 0


def test_select_refuses_an_ineligible_cpa(core_client, notify_user):
    core_client.list_cpa_ids.return_value = ["EXAMPLE-EBMS-BB-2-0_0001"]
    core_client.get_cpa.return_value = make_cpa_xml(logius_endpoint=PREPROD_ENDPOINT)

    with pytest.raises(cpa_nl.CpaRejected, match="can't be used for live"):
        cpa_nl.select(CPA_PURPOSE_LIVE, "EXAMPLE-EBMS-BB-2-0_0001", message_type="bericht", user_id=notify_user.id)

    assert MessageboxCpaSelection.query.count() == 0
    assert MessageboxCpaSelectionHistory.query.count() == 0


def test_list_cpas_assesses_every_cpa_and_marks_selections(core_client, notify_user):
    create_messagebox_cpa_selection(CPA_PURPOSE_TEAM, updated_by=notify_user, cpa_id="PREPROD")
    core_client.list_cpa_ids.return_value = ["PREPROD", "BROKEN"]
    core_client.get_cpa.side_effect = lambda cpa_id: (
        make_cpa_xml(cpa_id="PREPROD") if cpa_id == "PREPROD" else "<not-a-cpa"
    )

    preprod, broken = cpa_nl.list_cpas()

    assert preprod.selected_for == [CPA_PURPOSE_TEAM]
    assert preprod.assessments[CPA_PURPOSE_TEAM].eligible
    assert not preprod.assessments[CPA_PURPOSE_LIVE].eligible
    assert broken.error.startswith("CPA is not well-formed")
    assert broken.assessments == {}
    core_client.validate_cpa.assert_not_called()


def test_assess_lets_a_cpa_that_has_not_started_yet_be_uploaded_but_not_selected():
    summary = cpa_nl.parse_cpa_summary(make_cpa_xml(start="2026-11-24T08:00:00Z"))

    for_upload = cpa_nl.assess(summary, CPA_PURPOSE_TEAM, now=NOW, for_selection=False)
    for_selection = cpa_nl.assess(summary, CPA_PURPOSE_TEAM, now=NOW)

    assert for_upload.eligible
    assert "it can be selected from 2026-11-24" in for_upload.checks[-1].message
    assert _failed_checks(for_selection) == [cpa_nl.CHECK_PERIOD]


def test_upload_inserts_a_cpa_that_starts_later(core_client):
    cpa_xml = make_cpa_xml(start="2099-01-01T00:00:00Z", end="2099-12-31T00:00:00Z")

    cpa_nl.upload(cpa_xml, CPA_PURPOSE_TEAM)

    core_client.insert_cpa.assert_called_once_with(cpa_xml, overwrite=False)


def test_upload_refuses_a_cpa_that_has_ended(core_client):
    with pytest.raises(cpa_nl.CpaRejected):
        cpa_nl.upload(make_cpa_xml(end="2026-01-02T00:00:00Z"), CPA_PURPOSE_TEAM)

    core_client.insert_cpa.assert_not_called()
