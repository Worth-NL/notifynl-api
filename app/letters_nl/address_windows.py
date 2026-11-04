"""
The address windows precompiled letters are checked against, one of which every sanitise and overlay request to
template-preview carries (its app/address_window_nl.py).

The standard windows are template-preview's own 50mm/60mm geometry. A print provider with its own envelope window
gets an entry too: the area its address has to sit in, and the postage area around it in which nothing but the
address may be printed. LETTER_ADDRESS_WINDOWS is the single source; letter_address_window_for is the one lookup, so
the windows can later come from somewhere else (configuration, the provider) without touching its callers.
"""

from dataclasses import asdict, dataclass

from flask import current_app

from app.letters_nl.constants import LETTER_PROVIDER_PINGEN, PINGEN_ADDRESS_PLACEMENT

# The standard window for a placement that has none, as template-preview falls back to its
# DEFAULT_LETTER_ADDRESS_PLACEMENT
DEFAULT_ADDRESS_PLACEMENT = "60mm"


@dataclass(frozen=True)
class Area:
    """A rectangle in mm, measured from the top left corner of the page."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class LetterAddressWindow:
    id: str
    address_placement: str
    address_area: Area
    postage_area: Area | None = None
    provider: str | None = None

    def to_dict(self):
        return asdict(self)


LETTER_ADDRESS_WINDOWS = [
    LetterAddressWindow(
        id="standard-50mm",
        address_placement="50mm",
        address_area=Area(x=24.6, y=50, width=95.4, height=40),
    ),
    LetterAddressWindow(
        id="standard-60mm",
        address_placement="60mm",
        address_area=Area(x=24.6, y=60, width=95.4, height=40),
    ),
    # Pingen's document check for left-windowed envelopes: the address inside its Address Area, nothing else inside its
    # Postage Area. The measurements are on https://help.pingen.com/en/templates-and-postal-requirements/layout-requirements
    # ("Address area", "Postage area"), the rule on
    # https://help.pingen.com/en/fix-and-enhance-letters/issue-with-recipient-address
    LetterAddressWindow(
        id="pingen",
        provider=LETTER_PROVIDER_PINGEN,
        address_placement=PINGEN_ADDRESS_PLACEMENT,
        address_area=Area(x=22, y=60, width=85.5, height=25.5),
        postage_area=Area(x=20, y=40, width=89.5, height=47.5),
    ),
]


def letter_address_window_for(provider, address_placement):
    """The print provider's own window if it has one, otherwise the standard window for the placement."""
    for window in LETTER_ADDRESS_WINDOWS:
        if provider and window.provider == provider:
            return window
    standard_windows = {window.address_placement: window for window in LETTER_ADDRESS_WINDOWS if not window.provider}
    if address_placement in standard_windows:
        return standard_windows[address_placement]
    # placements are validated when they're set, so this means one was added without a window
    current_app.logger.warning(
        "No letter address window for placement %s, using the %s one", address_placement, DEFAULT_ADDRESS_PLACEMENT
    )
    return standard_windows[DEFAULT_ADDRESS_PLACEMENT]
