"""The record the scraper produces."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field, fields
from typing import Optional


@dataclass
class Listing:
    """A single bina.az listing.

    The four fields the report is built on are ``price``, ``area``, ``rooms``
    and the location trio (``location_raw`` / ``district`` / ``metro``).
    Everything else is provenance: where the row came from and how much of it
    we trust.
    """

    listing_id: str
    url: str = ""
    title: str = ""

    price: Optional[float] = None
    currency: Optional[str] = None

    area: Optional[float] = None  # m²
    rooms: Optional[int] = None

    location_raw: str = ""
    district: str = ""
    metro: str = ""
    settlement: str = ""

    floor: Optional[int] = None
    floors_total: Optional[int] = None

    posted_at: Optional[dt.date] = None
    # Which label the date came from: "created", "updated", or "" if unknown.
    # bina.az bumps listings, so an "updated" date is not a posting date and
    # the report says so rather than quietly mixing the two.
    date_source: str = ""

    scraped_at: Optional[dt.datetime] = None
    source_page: Optional[int] = None
    detail_fetched: bool = False

    @property
    def price_per_m2(self) -> Optional[float]:
        if self.price and self.area and self.area > 0:
            return self.price / self.area
        return None

    def merge(self, other: "Listing") -> "Listing":
        """Overlay non-empty values from ``other`` onto a copy of ``self``."""
        merged = Listing(**asdict(self))
        for f in fields(Listing):
            value = getattr(other, f.name)
            if value not in (None, "", False):
                setattr(merged, f.name, value)
        return merged


@dataclass
class ParseReport:
    """How well a page parsed — used by ``bina inspect`` and run summaries."""

    cards_found: int = 0
    with_price: int = 0
    with_area: int = 0
    with_rooms: int = 0
    with_location: int = 0
    notes: list = field(default_factory=list)

    def observe(self, listing: Listing) -> None:
        self.cards_found += 1
        self.with_price += listing.price is not None
        self.with_area += listing.area is not None
        self.with_rooms += listing.rooms is not None
        self.with_location += bool(listing.location_raw)

    def coverage(self) -> dict:
        total = self.cards_found or 1
        return {
            "price": self.with_price / total,
            "area": self.with_area / total,
            "rooms": self.with_rooms / total,
            "location": self.with_location / total,
        }
