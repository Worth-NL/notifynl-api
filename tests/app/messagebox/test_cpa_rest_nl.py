import pytest
from ebms_adapter_client import EbmsConnectionError, EbmsServerError
from flask import current_app

from app.messagebox.constants import CPA_PURPOSE_LIVE, CPA_PURPOSE_TEAM
from app.models_nl import MessageboxCpaSelection
from tests.app.db_nl import create_messagebox_cpa_selection
from tests.app.messagebox.cpa_xml_nl import LIVE_ENDPOINT, OWN_ENDPOINT, make_cpa_xml


@pytest.fixture(autouse=True)
def cpa_config(notify_api, mocker):
    # patch.dict, not set_config_values: it removes keys the "test" config doesn't have once the test is done
    mocker.patch.dict(
        current_app.config,
        {
            "EBMS_PUBLIC_ENDPOINT": OWN_ENDPOINT,
            "EBMS_LIVE_ENDPOINT_HOSTS": ("globe-ebms-internet.procesinfrastructuur.nl",),
            "EBMS_PREPROD_ENDPOINT_HOSTS": ("preprod-globe-ebms-*.procesinfrastructuur.nl",),
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


def test_get_cpas_lists_each_cpa_with_its_assessments(admin_request, core_client, notify_user):
    create_messagebox_cpa_selection(CPA_PURPOSE_TEAM, updated_by=notify_user, cpa_id="PREPROD")
    core_client.list_cpa_ids.return_value = ["PREPROD"]
    core_client.get_cpa.return_value = make_cpa_xml(cpa_id="PREPROD")

    (cpa,) = admin_request.get("messagebox_cpa.get_messagebox_cpas")["data"]

    assert cpa["cpa_id"] == "PREPROD"
    assert cpa["selected_for"] == [CPA_PURPOSE_TEAM]
    assert cpa["assessments"][CPA_PURPOSE_TEAM]["eligible"] is True
    assert cpa["assessments"][CPA_PURPOSE_LIVE]["eligible"] is False
    assert [party["name"] for party in cpa["summary"]["parties"]] == ["Logius", "Example"]


def test_validate_returns_summary_and_assessment(admin_request, core_client):
    response = admin_request.post(
        "messagebox_cpa.validate_messagebox_cpa", _data={"cpa_xml": make_cpa_xml(), "purpose": CPA_PURPOSE_TEAM}
    )

    assert response["data"]["summary"]["cpa_id"] == "EXAMPLE-EBMS-BB-2-0_0001"
    assert response["data"]["assessment"]["eligible"] is True
    core_client.insert_cpa.assert_not_called()


def test_upload_returns_201_for_an_eligible_cpa(admin_request, core_client):
    admin_request.post(
        "messagebox_cpa.upload_messagebox_cpa",
        _data={"cpa_xml": make_cpa_xml(), "purpose": CPA_PURPOSE_TEAM},
        _expected_status=201,
    )

    core_client.insert_cpa.assert_called_once()


def test_upload_returns_400_with_the_failed_checks(admin_request, core_client):
    response = admin_request.post(
        "messagebox_cpa.upload_messagebox_cpa",
        _data={"cpa_xml": make_cpa_xml(logius_endpoint=LIVE_ENDPOINT), "purpose": CPA_PURPOSE_TEAM},
        _expected_status=400,
    )

    assert response["message"] == "The CPA can't be used for team"
    failed = [check["name"] for check in response["assessment"]["checks"] if not check["passed"]]
    assert failed == ["counterparty_endpoint"]
    core_client.insert_cpa.assert_not_called()


@pytest.mark.parametrize(
    ("cpa_kwargs", "failed_check"),
    [({"status": "proposed"}, "status"), ({"end": "2026-01-02T00:00:00Z"}, "period")],
    ids=["proposed", "expired"],
)
def test_upload_returns_400_for_a_cpa_ebms_core_would_answer_with_500(
    admin_request, core_client, cpa_kwargs, failed_check
):
    # ebms-core 2.20.2 refuses these with a 500; the guardrails refuse them first, so ebms-core isn't asked
    core_client.validate_cpa.side_effect = EbmsServerError("CPA refused", status_code=500)

    response = admin_request.post(
        "messagebox_cpa.upload_messagebox_cpa",
        _data={"cpa_xml": make_cpa_xml(**cpa_kwargs), "purpose": CPA_PURPOSE_TEAM},
        _expected_status=400,
    )

    assert [check["name"] for check in response["assessment"]["checks"] if not check["passed"]] == [failed_check]
    core_client.validate_cpa.assert_not_called()
    core_client.insert_cpa.assert_not_called()


def test_upload_returns_400_when_ebms_core_refuses_with_500(admin_request, core_client):
    core_client.validate_cpa.side_effect = EbmsServerError("CPA version 1.0 not supported!", status_code=500)

    response = admin_request.post(
        "messagebox_cpa.upload_messagebox_cpa",
        _data={"cpa_xml": make_cpa_xml(), "purpose": CPA_PURPOSE_TEAM},
        _expected_status=400,
    )

    failed = [check for check in response["assessment"]["checks"] if not check["passed"]]
    assert [check["name"] for check in failed] == ["ebms_core_validation"]
    assert "CPA version 1.0 not supported!" in failed[0]["message"]
    core_client.insert_cpa.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        {"cpa_xml": "<x/>"},
        {"cpa_xml": "<x/>", "purpose": "other"},
        {"cpa_xml": "", "purpose": CPA_PURPOSE_TEAM},
        {"cpa_xml": "<x/>", "purpose": CPA_PURPOSE_TEAM, "extra": True},
    ],
)
def test_upload_validates_the_request(admin_request, core_client, data):
    admin_request.post("messagebox_cpa.upload_messagebox_cpa", _data=data, _expected_status=400)

    core_client.validate_cpa.assert_not_called()


def test_ebms_core_unreachable_returns_502(admin_request, core_client):
    core_client.list_cpa_ids.side_effect = EbmsConnectionError("Could not reach ebms-core")

    response = admin_request.get("messagebox_cpa.get_messagebox_cpas", _expected_status=502)

    assert "Could not reach ebms-core" in response["message"]


def test_select_stores_the_selection(admin_request, core_client, notify_user):
    core_client.list_cpa_ids.return_value = ["PREPROD"]
    core_client.get_cpa.return_value = make_cpa_xml(cpa_id="PREPROD")

    response = admin_request.post(
        "messagebox_cpa.select_messagebox_cpa",
        purpose=CPA_PURPOSE_TEAM,
        _data={"cpa_id": "PREPROD", "message_type": "test-bericht", "updated_by_id": str(notify_user.id)},
    )

    assert response["data"]["cpa_id"] == "PREPROD"
    assert response["data"]["updated_by_id"] == str(notify_user.id)
    assert MessageboxCpaSelection.query.one().purpose == CPA_PURPOSE_TEAM


def test_select_rejects_party_ids_sent_in_the_request(admin_request, core_client, notify_user):
    admin_request.post(
        "messagebox_cpa.select_messagebox_cpa",
        purpose=CPA_PURPOSE_TEAM,
        _data={
            "cpa_id": "PREPROD",
            "message_type": "test-bericht",
            "updated_by_id": str(notify_user.id),
            "to_party_id": "urn:osb:oin:99999999999999999999",
        },
        _expected_status=400,
    )

    assert MessageboxCpaSelection.query.count() == 0


def test_unknown_purpose_returns_404(admin_request, notify_user):
    admin_request.get("messagebox_cpa.get_messagebox_cpa_selection", purpose="other", _expected_status=404)


def test_get_selection_and_history(admin_request, core_client, notify_user):
    core_client.list_cpa_ids.return_value = ["FIRST", "SECOND"]
    for cpa_id in ("FIRST", "SECOND"):
        core_client.get_cpa.return_value = make_cpa_xml(cpa_id=cpa_id)
        admin_request.post(
            "messagebox_cpa.select_messagebox_cpa",
            purpose=CPA_PURPOSE_TEAM,
            _data={"cpa_id": cpa_id, "message_type": "test-bericht", "updated_by_id": str(notify_user.id)},
        )

    selection = admin_request.get("messagebox_cpa.get_messagebox_cpa_selection", purpose=CPA_PURPOSE_TEAM)["data"]
    history = admin_request.get("messagebox_cpa.get_messagebox_cpa_selection_history", purpose=CPA_PURPOSE_TEAM)

    assert selection["cpa_id"] == "SECOND"
    assert [entry["cpa_id"] for entry in history["data"]] == ["SECOND", "FIRST"]
    assert admin_request.get("messagebox_cpa.get_messagebox_cpa_selection", purpose=CPA_PURPOSE_LIVE)["data"] is None
