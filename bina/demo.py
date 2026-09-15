"""Synthetic listings, for checking the report layout without scraping.

Every number here is generated. Nothing in this module touches bina.az, and
reports built from it are labelled as synthetic.
"""

from __future__ import annotations

import datetime as dt
import random
from typing import Optional

from .models import Listing

# Real Baku district names, with invented price levels (AZN per m²).
DISTRICTS = [
    ("Nəsimi", 2100),
    ("Yasamal", 1950),
    ("Xətai", 1800),
    ("Nərimanov", 2050),
    ("Səbail", 3100),
    ("Binəqədi", 1350),
    ("Nizami", 1600),
    ("Suraxanı", 1050),
    ("Xəzər", 900),
    ("Sabunçu", 1000),
    ("Qaradağ", 850),
    ("Pirallahı", 780),
]

METROS = ["Xətai", "Elmlər Akademiyası", "Nizami", "28 May", "Gənclik", "Memar Əcəmi"]


def synthetic_listings(
    count: int = 1200,
    since: Optional[dt.date] = None,
    until: Optional[dt.date] = None,
    seed: int = 7,
) -> list[Listing]:
    rng = random.Random(seed)
    until = until or dt.date.today()
    since = since or until - dt.timedelta(days=365)
    span = max((until - since).days, 1)

    listings: list[Listing] = []
    for index in range(count):
        district, base_ppm = DISTRICTS[
            min(int(abs(rng.gauss(0, 3.2))), len(DISTRICTS) - 1)
        ]
        rooms = min(max(1, int(abs(rng.gauss(2.4, 1.1)) + 0.5)), 6)
        area = max(28.0, rng.gauss(22 + rooms * 22, 12))

        # Newer listings skew slightly pricier, so the trend chart has a slope.
        age_days = int(rng.triangular(0, span, span * 0.25))
        posted = until - dt.timedelta(days=age_days)
        drift = 1 + 0.09 * (1 - age_days / span)
        ppm = base_ppm * drift * rng.gauss(1.0, 0.13)
        price = round(max(ppm, 300) * area, -2)

        listings.append(
            Listing(
                listing_id=str(4_000_000 + index),
                url=f"https://bina.az/items/{4_000_000 + index}",
                title=f"{rooms} otaqlı {'yeni tikili' if rng.random() > 0.4 else 'köhnə tikili'}",
                price=float(price),
                currency="AZN",
                area=round(area, 1),
                rooms=rooms,
                location_raw=f"{district} r. {rng.choice(METROS)} m.",
                district=district,
                metro=rng.choice(METROS),
                floor=rng.randint(1, 16),
                floors_total=rng.randint(5, 20),
                posted_at=posted,
                date_source="created",
                scraped_at=dt.datetime.now(),
                detail_fetched=True,
            )
        )
    return listings
