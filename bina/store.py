"""SQLite storage, so a crawl can be stopped and resumed."""

from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    listing_id    TEXT PRIMARY KEY,
    url           TEXT,
    title         TEXT,
    price         REAL,
    currency      TEXT,
    area          REAL,
    rooms         INTEGER,
    location_raw  TEXT,
    district      TEXT,
    metro         TEXT,
    settlement    TEXT,
    floor         INTEGER,
    floors_total  INTEGER,
    posted_at     TEXT,
    date_source   TEXT,
    scraped_at    TEXT,
    source_page   INTEGER,
    detail_fetched INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS listings_posted_at ON listings(posted_at);
CREATE INDEX IF NOT EXISTS listings_district ON listings(district);
CREATE INDEX IF NOT EXISTS listings_detail ON listings(detail_fetched);

CREATE TABLE IF NOT EXISTS pages (
    section     TEXT NOT NULL,
    page        INTEGER NOT NULL,
    fetched_at  TEXT,
    cards_found INTEGER,
    PRIMARY KEY (section, page)
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT,
    finished_at TEXT,
    section     TEXT,
    pages       INTEGER,
    listings    INTEGER,
    details     INTEGER,
    note        TEXT
);
"""

_COLUMNS = (
    "listing_id url title price currency area rooms location_raw district metro "
    "settlement floor floors_total posted_at date_source scraped_at source_page "
    "detail_fetched"
).split()


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- writing ---------------------------------------------------------

    def upsert_listings(self, listings: Iterable[Listing]) -> int:
        rows = [self._to_row(listing) for listing in listings]
        if not rows:
            return 0
        placeholders = ", ".join("?" * len(_COLUMNS))
        # COALESCE keeps a previously-parsed value when this pass saw nothing,
        # so a card-only re-crawl never erases detail-page data.
        updates = ", ".join(
            f"{col}=COALESCE(excluded.{col}, {col})" for col in _COLUMNS if col != "listing_id"
        )
        self.conn.executemany(
            f"INSERT INTO listings ({', '.join(_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(listing_id) DO UPDATE SET {updates}",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def record_page(self, section: str, page: int, cards_found: int) -> None:
        self.conn.execute(
            "INSERT INTO pages (section, page, fetched_at, cards_found) VALUES (?,?,?,?) "
            "ON CONFLICT(section, page) DO UPDATE SET fetched_at=excluded.fetched_at, "
            "cards_found=excluded.cards_found",
            (section, page, dt.datetime.now().isoformat(timespec="seconds"), cards_found),
        )
        self.conn.commit()

    def pages_done(self, section: str) -> set[int]:
        cursor = self.conn.execute("SELECT page FROM pages WHERE section=?", (section,))
        return {row["page"] for row in cursor}

    def start_run(self, section: str) -> int:
        cursor = self.conn.execute(
            "INSERT INTO runs (started_at, section) VALUES (?,?)",
            (dt.datetime.now().isoformat(timespec="seconds"), section),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, pages: int, listings: int, details: int, note: str = "") -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, pages=?, listings=?, details=?, note=? WHERE id=?",
            (
                dt.datetime.now().isoformat(timespec="seconds"),
                pages,
                listings,
                details,
                note,
                run_id,
            ),
        )
        self.conn.commit()

    # -- reading ---------------------------------------------------------

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS n FROM listings").fetchone()["n"])

    def needs_detail(self, limit: Optional[int] = None) -> list[str]:
        """Listing ids with no posting date yet, newest-seen first."""
        sql = (
            # detail_fetched is stored as 1-or-NULL so that COALESCE on upsert
            # never downgrades a fetched row, hence the NULL check here.
            "SELECT listing_id FROM listings "
            "WHERE posted_at IS NULL AND (detail_fetched IS NULL OR detail_fetched = 0) "
            "ORDER BY source_page IS NULL, source_page, listing_id DESC"
        )
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [row["listing_id"] for row in self.conn.execute(sql)]

    def iter_listings(
        self,
        since: Optional[dt.date] = None,
        until: Optional[dt.date] = None,
        include_undated: bool = False,
    ) -> Iterator[Listing]:
        clauses, params = [], []
        if since or until:
            date_clause = []
            if since:
                date_clause.append("posted_at >= ?")
                params.append(since.isoformat())
            if until:
                date_clause.append("posted_at <= ?")
                params.append(until.isoformat())
            joined = " AND ".join(date_clause)
            clauses.append(f"(({joined})" + (" OR posted_at IS NULL)" if include_undated else ")"))
        elif not include_undated:
            clauses.append("posted_at IS NOT NULL")

        sql = f"SELECT * FROM listings{' WHERE ' + ' AND '.join(clauses) if clauses else ''}"
        for row in self.conn.execute(sql, params):
            yield self._from_row(row)

    def close(self) -> None:
        self.conn.close()

    # -- row mapping -----------------------------------------------------

    @staticmethod
    def _to_row(listing: Listing) -> tuple:
        return (
            listing.listing_id,
            listing.url or None,
            listing.title or None,
            listing.price,
            listing.currency,
            listing.area,
            listing.rooms,
            listing.location_raw or None,
            listing.district or None,
            listing.metro or None,
            listing.settlement or None,
            listing.floor,
            listing.floors_total,
            listing.posted_at.isoformat() if listing.posted_at else None,
            listing.date_source or None,
            listing.scraped_at.isoformat(timespec="seconds") if listing.scraped_at else None,
            listing.source_page,
            1 if listing.detail_fetched else None,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Listing:
        posted = row["posted_at"]
        scraped = row["scraped_at"]
        return Listing(
            listing_id=row["listing_id"],
            url=row["url"] or "",
            title=row["title"] or "",
            price=row["price"],
            currency=row["currency"],
            area=row["area"],
            rooms=row["rooms"],
            location_raw=row["location_raw"] or "",
            district=row["district"] or "",
            metro=row["metro"] or "",
            settlement=row["settlement"] or "",
            floor=row["floor"],
            floors_total=row["floors_total"],
            posted_at=dt.date.fromisoformat(posted) if posted else None,
            date_source=row["date_source"] or "",
            scraped_at=dt.datetime.fromisoformat(scraped) if scraped else None,
            source_page=row["source_page"],
            detail_fetched=bool(row["detail_fetched"]),
        )


def export_csv(listings: Iterable[Listing], path: str | Path) -> int:
    """Write listings to CSV; returns the row count."""
    import csv

    rows = list(listings)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "listing_id",
        "url",
        "posted_at",
        "date_source",
        "price",
        "currency",
        "area_m2",
        "price_per_m2",
        "rooms",
        "location_raw",
        "district",
        "metro",
        "floor",
        "floors_total",
        "title",
    ]
    with closing(path.open("w", newline="", encoding="utf-8")) as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for listing in rows:
            ppm = listing.price_per_m2
            writer.writerow(
                [
                    listing.listing_id,
                    listing.url,
                    listing.posted_at.isoformat() if listing.posted_at else "",
                    listing.date_source,
                    listing.price if listing.price is not None else "",
                    listing.currency or "",
                    listing.area if listing.area is not None else "",
                    f"{ppm:.2f}" if ppm else "",
                    listing.rooms if listing.rooms is not None else "",
                    listing.location_raw,
                    listing.district,
                    listing.metro,
                    listing.floor if listing.floor is not None else "",
                    listing.floors_total if listing.floors_total is not None else "",
                    listing.title,
                ]
            )
    return len(rows)
