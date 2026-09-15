"""Parse a bina.az search-results page into listing stubs."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from .. import selectors as sel
from ..models import ListingStub
from . import normalize as nz
from .soup import attr_of, make_soup, select_all, select_first, text_of

_AREA_RE = re.compile(r"m²|m2|kv\.?\s*m", re.IGNORECASE)
_SOT_RE = re.compile(r"\bsot\b", re.IGNORECASE)
_ROOM_RE = re.compile(r"otaq", re.IGNORECASE)
_FLOOR_RE = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")


def _assign_param(stub: ListingStub, text: str) -> None:
    """Route one card parameter to its field, keyed on the unit it carries.

    The strip is read by unit rather than by position because bina.az omits
    entries (land plots have no room count, for instance) and a positional read
    would then shift every following value into the wrong field.
    """
    if _ROOM_RE.search(text):
        stub.rooms = nz.parse_rooms(text)
    elif _FLOOR_RE.match(text):
        stub.floor, stub.floors_total = nz.parse_floor(text)
    elif _AREA_RE.search(text) or _SOT_RE.search(text):
        # Land plots are quoted in sot; keep them out of the m² field.
        if not _SOT_RE.search(text):
            stub.area_m2 = nz.parse_area(text)


def parse_card(card, base_url: str = sel.BASE_URL) -> ListingStub | None:
    """Parse one search-result card. Returns None if it carries no item id."""
    href = attr_of(card, sel.LISTING["card_link"], ("href",))
    item_id = nz.item_id_from_url(href)
    if not item_id:
        return None

    stub = ListingStub(item_id=item_id, url=urljoin(base_url, href))
    stub.title = text_of(card, sel.LISTING["card_title"])

    price_text = text_of(card, sel.LISTING["card_price"])
    currency_text = text_of(card, sel.LISTING["card_currency"])
    # The currency is a child <span> of the price node, so its text is already
    # inside price_text; pass both so either markup shape works.
    stub.price, stub.currency = nz.parse_price(
        " ".join(part for part in (price_text, currency_text) if part)
    )

    for param in select_all(card, sel.LISTING["card_params"]):
        text = nz.clean_text(param.get_text(" ", strip=True))
        if text:
            _assign_param(stub, text)

    stub.location = text_of(card, sel.LISTING["card_location"])
    stub.listed_at = nz.parse_az_date(text_of(card, sel.LISTING["card_footer"]))

    photo = select_first(card, sel.LISTING["card_photo"])
    if photo is not None:
        src = photo.get("src") or photo.get("data-src")
        if src:
            stub.photo_url = urljoin(base_url, str(src))

    badges = " ".join(
        nz.fold(badge.get_text(" ", strip=True))
        for badge in select_all(card, sel.LISTING["card_badges"])
    )
    if badges:
        if "cixaris" in badges:
            stub.has_bill_of_sale = True
        if "ipoteka" in badges:
            stub.has_mortgage = True
    return stub


def parse_listing_page(html: str, base_url: str = sel.BASE_URL) -> list[ListingStub]:
    """Parse every card on a search-results page, in document order."""
    soup = make_soup(html)
    stubs: list[ListingStub] = []
    seen: set[str] = set()
    for card in select_all(soup, sel.LISTING["card"]):
        stub = parse_card(card, base_url)
        # bina.az repeats promoted listings above the organic results.
        if stub and stub.item_id not in seen:
            seen.add(stub.item_id)
            stubs.append(stub)
    return stubs


def find_next_page_url(html: str, base_url: str = sel.BASE_URL) -> str | None:
    """The href of the "next page" link, or None on the last page."""
    soup = make_soup(html)
    href = attr_of(soup, sel.LISTING["pagination_next"], ("href",))
    return urljoin(base_url, href) if href else None
