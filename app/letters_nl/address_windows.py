"""
The address windows precompiled letters are checked against, one of which every sanitise and overlay request to
template-preview carries (its app/address_window_nl.py).

The standard windows are template-preview's own 50mm/60mm geometry. A print provider with its own envelope window
gets an entry too: the area its address has to sit in, and the postage area around it in which nothing but the
address may be printed. LETTER_ADDRESS_WINDOWS is the single source; letter_address_window_for is the one lookup, so
the windows can later come from somewhere else (configuration, the provider) without touching its callers.
"""

from dataclasses import asdict, dataclass

from app.letters_nl.constants import LETTER_PROVIDER_PINGEN, PINGEN_ADDRESS_PLACEMENT


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
    # Pingen's document check: the address inside its Address Area, nothing else inside its Postage Area
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
    for window in LETTER_ADDRESS_WINDOWS:
        if not window.provider and window.address_placement == address_placement:
            return window
    return next(window for window in LETTER_ADDRESS_WINDOWS if window.id == f"standard-{PINGEN_ADDRESS_PLACEMENT}")
