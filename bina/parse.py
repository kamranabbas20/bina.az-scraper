"""Turn bina.az HTML into :class:`~bina.models.Listing` records.

The parsers never assume a fixed class name. A listing card is located by the
one thing bina.az cannot change without breaking its own links — an ``<a>``
pointing at ``/items/<id>`` — and the fields are read out of the card's visible
text. Class names are consulted only as hints, first.
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

from . import patterns as P
from .minidom import Node, parse_html
from .models import Listing, ParseReport

# How far to climb from an ``/items/<id>`` link when looking for the card that
# wraps it. Deep enough for a nested layout, shallow enough to never reach the
# results container.
MAX_CARD_DEPTH = 6


def parse_listing_page(
    markup: str,
    base_url: str = "https://bina.az/",
    page: Optional[int] = None,
    today: Optional[dt.date] = None,
) -> tuple[list[Listing], ParseReport]:
    """Parse a search-results page into listings."""
    root = parse_html(markup)
    report = ParseReport()
    now = dt.datetime.now()

    listings: dict[str, Listing] = {}
    for listing_id, card in _iter_cards(root):
        listing = _listing_from_card(listing_id, card, base_url, today)
        listing.source_page = page
        listing.scraped_at = now
        # The same listing can appear twice on a page (a VIP block plus the
        # regular results). Merge rather than letting the thinner copy win.
        if listing_id in listings:
            listings[listing_id] = listings[listing_id].merge(listing)
        else:
            listings[listing_id] = listing

    for listing in listings.values():
        report.observe(listing)

    if not listings:
        report.notes.append(
            "No /items/<id> links found. The page is probably a block/captcha "
            "page, or the results are rendered client-side."
        )
    else:
        for name, ratio in report.coverage().items():
            if ratio < 0.5:
                report.notes.append(
                    f"{name} parsed for only {ratio:.0%} of cards — the card "
                    f"markup likely changed; check bina/patterns.py"
                )

    return list(listings.values()), report


def parse_detail_page(
    markup: str,
    listing_id: str = "",
    base_url: str = "https://bina.az/",
    today: Optional[dt.date] = None,
) -> Listing:
    """Parse a listing detail page.

    The detail page is the only place the posting date appears, and it carries
    cleaner values for the other fields, so anything it yields overrides the
    card.
    """
    root = parse_html(markup)
    body = root.find(tag="body") or root
    text = body.text()

    listing = Listing(listing_id=listing_id, detail_fetched=True)
    listing.scraped_at = dt.datetime.now()

    if not listing.listing_id:
        link = _canonical_url(root)
        if link:
            match = P.ITEM_HREF.search(link)
            if match:
                listing.listing_id = match.group(1)
    if listing.listing_id:
        listing.url = urljoin(base_url, f"/items/{listing.listing_id}")

    title = root.find(tag="h1")
    if title:
        listing.title = title.text()

    _read_price(listing, _price_text(root) or text)
    _read_dimensions(listing, _parameters_text(root) or text)
    _read_location(listing, root, text)

    created = _labelled_date(text, P.CREATED_LABELS, today)
    if created:
        listing.posted_at, listing.date_source = created, "created"
    else:
        updated = _labelled_date(text, P.UPDATED_LABELS, today)
        if updated:
            listing.posted_at, listing.date_source = updated, "updated"
        else:
            loose = P.parse_date(text, today)
            if loose:
                listing.posted_at, listing.date_source = loose, "unlabelled"

    return listing


# --- card location ----------------------------------------------------------


def _iter_cards(root: Node) -> Iterable[tuple[str, Node]]:
    """Yield ``(listing_id, card_node)`` for every listing on the page."""
    anchors: list[tuple[str, Node]] = []
    for node in root.elements():
        if node.tag != "a":
            continue
        href = node.get("href") or ""
        match = P.ITEM_HREF.search(href)
        if match:
            anchors.append((match.group(1), node))

    seen: set[int] = set()
    for listing_id, anchor in anchors:
        card = _expand_to_card(anchor, listing_id)
        if id(card) in seen:
            continue
        seen.add(id(card))
        yield listing_id, card


def _expand_to_card(anchor: Node, listing_id: str) -> Node:
    """Climb from a listing link to the largest node that is still one card.

    The stopping rule is the reliable one: an ancestor that also contains a
    *different* listing's link is the results container, not a card.
    """
    card = anchor
    node = anchor.parent
    depth = 0
    while node is not None and depth < MAX_CARD_DEPTH:
        if _other_listing_ids(node, listing_id):
            break
        card = node
        node = node.parent
        depth += 1
    return card


def _other_listing_ids(node: Node, listing_id: str) -> bool:
    for child in node.elements():
        if child.tag != "a":
            continue
        match = P.ITEM_HREF.search(child.get("href") or "")
        if match and match.group(1) != listing_id:
            return True
    return False


# --- field extraction -------------------------------------------------------


def _listing_from_card(
    listing_id: str, card: Node, base_url: str, today: Optional[dt.date]
) -> Listing:
    listing = Listing(listing_id=listing_id, url=urljoin(base_url, f"/items/{listing_id}"))
    text = card.text()

    _read_price(listing, _price_text(card) or text)
    _read_dimensions(listing, _parameters_text(card) or text)
    _read_location(listing, card, text)

    name = card.find(cls_contains="name") or card.find(tag="h3") or card.find(tag="h2")
    if name:
        listing.title = name.text()

    # Some card layouts print a date; most do not. Take it when offered — it
    # saves a detail request.
    date = P.parse_date(text, today)
    if date:
        listing.posted_at, listing.date_source = date, "card"

    return listing


def _price_text(scope: Node) -> str:
    node = scope.find(cls_contains="price")
    return node.text() if node else ""


def _parameters_text(scope: Node) -> str:
    node = (
        scope.find(cls_contains="parameters")
        or scope.find(cls_contains="params")
        or scope.find(tag="table")
    )
    return node.text() if node else ""


def _read_price(listing: Listing, text: str) -> None:
    match = P.PRICE.search(text)
    if not match:
        return
    value = P.clean_number(match.group(1))
    if value is None or value <= 0:
        return
    listing.price = value
    listing.currency = P.CURRENCIES.get(match.group(2).upper(), match.group(2).upper())


def _read_dimensions(listing: Listing, text: str) -> None:
    match = P.AREA.search(text)
    if match:
        area = P.clean_number(match.group(1))
        if area and area > 0:
            listing.area = area

    match = P.ROOMS.search(text)
    if match:
        listing.rooms = int(match.group(1))

    match = P.FLOOR_OF.search(text)
    if match:
        listing.floor = int(match.group(1))
        listing.floors_total = int(match.group(2))
    else:
        match = P.FLOOR_ONLY.search(text)
        if match:
            listing.floor = int(match.group(1))


def _read_location(listing: Listing, scope: Node, fallback_text: str) -> None:
    node = scope.find(cls_contains="location") or scope.find(cls_contains="address")
    raw = node.text() if node else ""

    if not raw:
        # No location element: find the text fragment that looks like one.
        for candidate in scope.elements():
            snippet = candidate.text()
            if not snippet or len(snippet) > 80:
                continue
            if P.DISTRICT.search(snippet) or P.METRO.search(snippet) or P.SETTLEMENT.search(snippet):
                raw = snippet
                break

    search_space = raw or fallback_text
    listing.location_raw = raw.strip()

    match = P.DISTRICT.search(search_space)
    if match:
        listing.district = _tidy(match.group(1))
    match = P.METRO.search(search_space)
    if match:
        listing.metro = _tidy(match.group(1))
    match = P.SETTLEMENT.search(search_space)
    if match:
        listing.settlement = _tidy(match.group(1))

    if not listing.location_raw:
        parts = [listing.district and f"{listing.district} r.", listing.metro and f"{listing.metro} m."]
        listing.location_raw = " ".join(p for p in parts if p)


def _tidy(value: str) -> str:
    return " ".join(value.split()).strip(" ,.-")


def _labelled_date(text: str, labels, today: Optional[dt.date]) -> Optional[dt.date]:
    """Find a date that follows one of ``labels`` within a short window."""
    lowered = text.lower()
    for label in labels:
        start = lowered.find(label)
        while start != -1:
            window = text[start : start + len(label) + 40]
            date = P.parse_date(window, today)
            if date:
                return date
            start = lowered.find(label, start + 1)
    return None


def _canonical_url(root: Node) -> str:
    link = root.find(tag="link")
    for node in root.find_all(tag="link"):
        if (node.get("rel") or "").lower() == "canonical":
            return node.get("href") or ""
    return (link.get("href") if link else "") or ""


def looks_like_block_page(markup: str) -> bool:
    """Heuristic for Cloudflare/anti-bot interstitials."""
    lowered = markup.lower()
    markers = (
        "cf-browser-verification",
        "checking your browser",
        "captcha",
        "just a moment",
        "access denied",
    )
    return any(marker in lowered for marker in markers) and "/items/" not in lowered


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower()
