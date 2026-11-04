import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest
import requests_mock

from app.constants import INTERNATIONAL_LETTERS, LETTER_TYPE
from app.letters_nl.upload_validation_rest_nl import TEMPLATE_PREVIEW_TIMEOUT
from tests.app.db import create_service
from tests.conftest import set_config, set_config_values

TEMPLATE_PREVIEW = "http://localhost/notifications-template-preview"
PDF = b"%PDF-1.4 a letter"


@pytest.fixture
def template_preview(notify_api):
    with set_config_values(
        notify_api, {"TEMPLATE_PREVIEW_API_HOST": TEMPLATE_PREVIEW, "TEMPLATE_PREVIEW_API_KEY": "k"}
    ):
        with requests_mock.Mocker() as mocker:
            yield mocker


def _query(request):
    return {key: values[0] for key, values in parse_qs(urlparse(request.url).query).items()}


@pytest.mark.parametrize("template_preview_status", [200, 400])
def test_sanitise_letter_upload_passes_template_previews_answer_on(
    notify_api, admin_request, sample_service, template_preview, template_preview_status
):
    sanitise_result = {"message": None if template_preview_status == 200 else "address-placement-mismatch"}
    mock_sanitise = template_preview.post(
        f"{TEMPLATE_PREVIEW}/precompiled/sanitise", json=sanitise_result, status_code=template_preview_status
    )

    with set_config(notify_api, "LETTER_DELIVERY_VIA_PROVIDERS", True):
        response = admin_request.post(
            "letter_upload.sanitise_letter_upload",
            service_id=sample_service.id,
            _data={"file": base64.b64encode(PDF).decode(), "upload_id": "upload-1"},
        )

    assert response == {"status_code": template_preview_status, "data": sanitise_result}
    request = mock_sanitise.last_request
    assert request.body == PDF
    assert request.headers["Authorization"] == "Token k"
    assert request.timeout == TEMPLATE_PREVIEW_TIMEOUT
    query = _query(request)
    assert query["upload_id"] == "upload-1"
    # the service has no organisation, so its letters go to Pingen
    assert query["letter_address_placement"] == "60mm"
    window = json.loads(query["letter_address_window"])
    assert window["id"] == "pingen"
    assert window["address_area"] == {"x": 22, "y": 60, "width": 85.5, "height": 25.5}


def test_sanitise_letter_upload_without_providers_sends_the_services_own_placement(
    notify_api, admin_request, sample_service, template_preview
):
    sample_service.letter_address_placement = "50mm"
    mock_sanitise = template_preview.post(f"{TEMPLATE_PREVIEW}/precompiled/sanitise", json={"message": None})

    with set_config(notify_api, "LETTER_DELIVERY_VIA_PROVIDERS", False):
        admin_request.post(
            "letter_upload.sanitise_letter_upload",
            service_id=sample_service.id,
            _data={"file": base64.b64encode(PDF).decode(), "upload_id": "upload-1"},
        )

    query = _query(mock_sanitise.last_request)
    assert query["letter_address_placement"] == "50mm"
    assert json.loads(query["letter_address_window"])["id"] == "standard-50mm"


@pytest.mark.parametrize(
    "permissions, expected",
    [
        ([LETTER_TYPE, INTERNATIONAL_LETTERS], "true"),
        ([LETTER_TYPE], "false"),
    ],
)
def test_sanitise_letter_upload_allows_international_letters_by_the_services_permission(
    admin_request, notify_db_session, template_preview, permissions, expected
):
    service = create_service(service_name="international letters", service_permissions=permissions)
    mock_sanitise = template_preview.post(f"{TEMPLATE_PREVIEW}/precompiled/sanitise", json={"message": None})

    admin_request.post(
        "letter_upload.sanitise_letter_upload",
        service_id=service.id,
        _data={"file": base64.b64encode(PDF).decode(), "upload_id": "upload-1"},
    )

    assert _query(mock_sanitise.last_request)["allow_international_letters"] == expected


def test_sanitise_letter_upload_fails_when_template_preview_does(admin_request, sample_service, template_preview):
    template_preview.post(f"{TEMPLATE_PREVIEW}/precompiled/sanitise", status_code=500)

    admin_request.post(
        "letter_upload.sanitise_letter_upload",
        service_id=sample_service.id,
        _data={"file": base64.b64encode(PDF).decode(), "upload_id": "upload-1"},
        _expected_status=500,
    )


@pytest.mark.parametrize(
    "data",
    [
        {"upload_id": "upload-1"},
        {"file": base64.b64encode(PDF).decode()},
        {"file": "not base64!", "upload_id": "upload-1"},
        {"file": base64.b64encode(PDF).decode(), "upload_id": "upload-1", "letter_address_placement": "50mm"},
        # the API decides these from the service
        {"file": base64.b64encode(PDF).decode(), "upload_id": "upload-1", "allow_international_letters": True},
    ],
)
def test_sanitise_letter_upload_rejects_bad_requests(admin_request, sample_service, template_preview, data):
    admin_request.post(
        "letter_upload.sanitise_letter_upload", service_id=sample_service.id, _data=data, _expected_status=400
    )

    assert not template_preview.called


def test_overlay_letter_upload_page(notify_api, admin_request, sample_service, template_preview):
    mock_overlay = template_preview.post(f"{TEMPLATE_PREVIEW}/precompiled/overlay.png", content=b"\x89PNG")

    with set_config(notify_api, "LETTER_DELIVERY_VIA_PROVIDERS", True):
        response = admin_request.post(
            "letter_upload.overlay_letter_upload_page",
            service_id=sample_service.id,
            _data={"file": base64.b64encode(PDF).decode(), "page_number": 2},
        )

    assert response == {"png": base64.b64encode(b"\x89PNG").decode()}
    request = mock_overlay.last_request
    assert request.body == PDF
    assert request.timeout == TEMPLATE_PREVIEW_TIMEOUT
    query = _query(request)
    assert query["page_number"] == "2"
    assert json.loads(query["letter_address_window"])["id"] == "pingen"


def test_overlay_letter_upload_page_fails_when_template_preview_does(admin_request, sample_service, template_preview):
    template_preview.post(f"{TEMPLATE_PREVIEW}/precompiled/overlay.png", status_code=400, json={"message": "bad"})

    admin_request.post(
        "letter_upload.overlay_letter_upload_page",
        service_id=sample_service.id,
        _data={"file": base64.b64encode(PDF).decode(), "page_number": 1},
        _expected_status=500,
    )
