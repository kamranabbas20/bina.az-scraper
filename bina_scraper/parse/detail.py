"""Parse a bina.az item page (/items/<id>) into a full Listing."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from .. import selectors as sel
from ..models import Listing
from . import normalize as nz
from .soup import make_soup, select_all, select_first, text_of

# Patterns run against folded text (normalize.fold()), so they stay ASCII.
_VIEWS_RE = re.compile(r"baxis|goruntu|view")
_UPDATED_RE = re.compile(r"yenilendi|guncell|updated")
_POSTED_RE = re.compile(r"elanin tarixi|yerlesdirildi|tarix")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_property(listing: Listing, label: str, value: str) -> None:
    """Write one detail-page property row onto the listing."""
    listing.properties[label] = value
    field = sel.PROPERTY_LABELS.get(nz.fold(label))
    if field is None:
        return
    if field in sel.BOOLEAN_FIELDS:
        setattr(listing, field, nz.parse_bool(value))
    elif field == "area_m2":
        listing.area_m2 = nz.parse_area(value)
    elif field == "land_area_sot":
        listing.land_area_sot = nz.parse_number(value)
    elif field == "rooms":
        listing.rooms = nz.parse_rooms(value)
    elif field == "floor":
        listing.floor, listing.floors_total = nz.parse_floor(value)
    else:
        setattr(listing, field, value)


def _apply_stat(listing: Listing, text: str) -> None:
    """Read one row of the statistics block (views, posted/updated dates)."""
    folded = nz.fold(text)
    if _VIEWS_RE.search(folded):
        count = nz.parse_number(text)
        if count is not None:
            listing.view_count = int(count)
    elif _UPDATED_RE.search(folded):
        listing.updated_at = nz.parse_az_date(text)
    elif _POSTED_RE.search(folded) or nz.parse_az_date(text):
        listing.listed_at = listing.listed_at or nz.parse_az_date(text)


def _deal_type_from_url(url: str) -> str | None:
    # Longest path first: "/gunluk-kiraye" also contains "kiraye".
    paths = sorted(sel.SEARCH_PATHS.items(), key=lambda kv: len(kv[1]), reverse=True)
    for deal_type, path in paths:
        if path.strip("/") in url:
            return deal_type
    return None


def parse_detail(html: str, url: str, *, item_id: str | None = None) -> Listing:
    """Parse an item page.

    ``url`` is the page's own URL; it supplies the item id when the markup does
    not. Fields that cannot be found stay None rather than raising, so one
    changed selector costs a field instead of the whole crawl.
    """
    soup = make_soup(html)
    resolved_id = item_id or nz.item_id_from_url(url) or ""
    listing = Listing(item_id=resolved_id, url=url, scraped_at=_utc_now())
    listing.properties["_selector_revision"] = sel.SELECTOR_REVISION

    listing.title = text_of(soup, sel.DETAIL["title"])
    price_text = text_of(soup, sel.DETAIL["price"])
    currency_text = text_of(soup, sel.DETAIL["price_currency"])
    listing.price, listing.currency = nz.parse_price(
        " ".join(part for part in (price_text, currency_text) if part)
    )

    for row in select_all(soup, sel.DETAIL["property_row"]):
        label = text_of(row, sel.DETAIL["property_name"])
        value = text_of(row, sel.DETAIL["property_value"])
        if label and value:
            _apply_property(listing, label, value)

    listing.description = text_of(soup, sel.DETAIL["description"])
    listing.amenities = [
        text
        for text in (
            text_of(item) for item in select_all(soup, sel.DETAIL["amenity"])
        )
        if text
    ]

    photos: list[str] = []
    for img in select_all(soup, sel.DETAIL["photo"]):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy")
        if not src:
            continue
        absolute = urljoin(sel.BASE_URL, str(src))
        if absolute not in photos:
            photos.append(absolute)
    listing.photo_urls = photos
    listing.photo_count = len(photos) or None

    listing.seller_name = text_of(soup, sel.DETAIL["seller_name"])
    seller_note = nz.fold(text_of(soup, sel.DETAIL["seller_type"]))
    if any(word in seller_note for word in sel.AGENT_WORDS):
        listing.seller_type = "agent"
    elif any(word in seller_note for word in sel.OWNER_WORDS):
        listing.seller_type = "owner"

    for stat in select_all(soup, sel.DETAIL["stats_row"]):
        text = text_of(stat)
        if text:
            _apply_stat(listing, text)

    map_node = select_first(soup, sel.DETAIL["map"])
    if map_node is not None:
        lat = map_node.get("data-lat") or map_node.get("data-latitude")
        lng = map_node.get("data-lng") or map_node.get("data-longitude")
        listing.latitude = nz.parse_number(str(lat)) if lat else None
        listing.longitude = nz.parse_number(str(lng)) if lng else None

    crumbs = [
        text for text in (text_of(c) for c in select_all(soup, sel.DETAIL["breadcrumb"])) if text
    ]
    if crumbs and not listing.category:
        listing.category = crumbs[-1]

    listing.deal_type = _deal_type_from_url(url)
    if not listing.deal_type and crumbs:
        joined = nz.fold(" ".join(crumbs))
        for word, deal_type in sel.DEAL_TYPE_WORDS:
            if word in joined:
                listing.deal_type = deal_type
                break

    parts = nz.split_location(listing.address or listing.location)
    listing.city = listing.city or parts["city"]
    listing.district = listing.district or parts["district"]
    listing.metro = listing.metro or parts["metro"]
    if parts["address"] and not listing.address:
        listing.address = parts["address"]
    return listing
