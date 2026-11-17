import pytest

from app.letters_nl.address_windows import LETTER_ADDRESS_WINDOWS, letter_address_window_for
from app.letters_nl.constants import LETTER_PROVIDER_PINGEN, LETTER_PROVIDER_REST_ENDPOINT


@pytest.mark.parametrize(
    "provider, address_placement, expected",
    [
        (LETTER_PROVIDER_PINGEN, "60mm", "pingen"),
        # Pingen's window doesn't depend on a placement
        (LETTER_PROVIDER_PINGEN, "50mm", "pingen"),
        # a REST endpoint has no window of its own: the standard one for its placement
        (LETTER_PROVIDER_REST_ENDPOINT, "50mm", "standard-50mm"),
        (LETTER_PROVIDER_REST_ENDPOINT, "60mm", "standard-60mm"),
        # letters through DVLA: no provider
        (None, "50mm", "standard-50mm"),
        (None, "60mm", "standard-60mm"),
    ],
)
def test_letter_address_window_for(provider, address_placement, expected):
    assert letter_address_window_for(provider, address_placement).id == expected


@pytest.mark.parametrize("address_placement", [None, "70mm"])
def test_letter_address_window_for_a_placement_without_a_window_is_the_default_one(caplog, address_placement):
    assert letter_address_window_for(None, address_placement).id == "standard-60mm"
    assert f"No letter address window for placement {address_placement}, using the 60mm one" in caplog.messages


def test_pingen_window_is_pingens_address_and_postage_area():
    assert letter_address_window_for(LETTER_PROVIDER_PINGEN, "60mm").to_dict() == {
        "id": "pingen",
        "provider": "pingen",
        "address_placement": "60mm",
        "address_area": {"x": 22, "y": 60, "width": 85.5, "height": 25.5},
        "postage_area": {"x": 20, "y": 40, "width": 89.5, "height": 47.5},
    }


@pytest.mark.parametrize("address_placement, top", [("50mm", 50), ("60mm", 60)])
def test_standard_windows_are_template_previews_own_geometry(address_placement, top):
    # notifynl-template-preview's app/precompiled.py: ADDRESS_LEFT/RIGHT_FROM_LEFT_OF_PAGE 24.6/120,
    # ADDRESS_TOP_FROM_TOP_OF_PAGE_BY_PLACEMENT, ADDRESS_WINDOW_HEIGHT 40
    assert letter_address_window_for(None, address_placement).to_dict() == {
        "id": f"standard-{address_placement}",
        "provider": None,
        "address_placement": address_placement,
        "address_area": {"x": 24.6, "y": top, "width": 95.4, "height": 40},
        "postage_area": None,
    }


def test_letter_address_window_ids_are_unique():
    ids = [window.id for window in LETTER_ADDRESS_WINDOWS]
    assert len(ids) == len(set(ids))
