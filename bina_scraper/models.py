"""Data structures for scraped records."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

# Fields left out of a listing's fingerprint. These move on their own between
# crawls, so including them would report every listing as changed and make the
# "changes" store mode no smaller than a full observation log.
FINGERPRINT_EXCLUDE = frozenset({"scraped_at", "content_hash", "view_count"})

# Keys inside .properties that the scraper writes itself rather than reading
# off the page; bumping SELECTOR_REVISION must not look like a price change.
FINGERPRINT_EXCLUDE_PROPERTIES = frozenset({"_selector_revision", "_source"})


@dataclass(slots=True)
class ListingStub:
    """What a search-results card gives us, before visiting the detail page."""

    item_id: str
    url: str
    title: str | None = None
    price: float | None = None
    currency: str | None = None
    rooms: int | None = None
    area_m2: float | None = None
    floor: int | None = None
    floors_total: int | None = None
    location: str | None = None
    listed_at: str | None = None
    has_bill_of_sale: bool | None = None
    has_mortgage: bool | None = None
    photo_url: str | None = None


@dataclass(slots=True)
class Listing:
    """A full record: card fields plus everything from the detail page."""

    item_id: str
    url: str
    scraped_at: str
    source: str = "bina.az"

    title: str | None = None
    price: float | None = None
    currency: str | None = None
    deal_type: str | None = None  # "sale" | "rent" | "rent_daily"
    category: str | None = None  # "Yeni tikili", "Həyət evi", ...
    rooms: int | None = None
    area_m2: float | None = None
    land_area_sot: float | None = None
    floor: int | None = None
    floors_total: int | None = None

    city: str | None = None
    district: str | None = None
    metro: str | None = None
    address: str | None = None
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    has_repair: bool | None = None
    has_bill_of_sale: bool | None = None
    has_mortgage: bool | None = None

    description: str | None = None
    amenities: list[str] = field(default_factory=list)
    photo_urls: list[str] = field(default_factory=list)
    photo_count: int | None = None

    seller_name: str | None = None
    seller_type: str | None = None  # "owner" | "agent"
    listed_at: str | None = None
    updated_at: str | None = None
    view_count: int | None = None

    # Raw label -> value straight off the detail page, so nothing is silently
    # dropped when bina.az adds a property we do not model yet.
    properties: dict[str, str] = field(default_factory=dict)

    # Digest of the fields above that describe the listing rather than the
    # crawl. Two observations of one listing share it iff nothing changed.
    content_hash: str | None = None

    def fingerprint(self) -> str:
        """Stable digest of the listing's own content.

        Used to tell one observation of an unchanged listing from a real
        change. Excludes the crawl timestamp and the view counter, which move
        on every crawl on their own.
        """
        payload = {
            key: value
            for key, value in dataclasses.asdict(self).items()
            if key not in FINGERPRINT_EXCLUDE
        }
        payload["properties"] = {
            key: value
            for key, value in self.properties.items()
            if key not in FINGERPRINT_EXCLUDE_PROPERTIES
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]

    def to_dict(self) -> dict[str, Any]:
        """Serialise, filling in the content hash if it is not set yet."""
        if self.content_hash is None:
            self.content_hash = self.fingerprint()
        return dataclasses.asdict(self)

    def merge_stub(self, stub: ListingStub) -> None:
        """Fill blanks from the search-results card.

        The detail page is authoritative; a card value is only used where the
        detail page gave us nothing.
        """
        for name in (
            "title",
            "price",
            "currency",
            "rooms",
            "area_m2",
            "floor",
            "floors_total",
            "location",
            "listed_at",
            "has_bill_of_sale",
            "has_mortgage",
        ):
            if getattr(self, name) in (None, "") and getattr(stub, name) is not None:
                setattr(self, name, getattr(stub, name))
        if stub.photo_url and not self.photo_urls:
            self.photo_urls = [stub.photo_url]
