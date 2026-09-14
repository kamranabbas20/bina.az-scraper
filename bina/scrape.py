"""Crawl orchestration: pages of cards, then detail pages for the dates."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urljoin

from .fetch import FetchConfig, Fetcher, FetchError, RobotsDisallowed
from .parse import looks_like_block_page, parse_detail_page, parse_listing_page
from .store import Store

log = logging.getLogger("bina.scrape")

# bina.az sections. "alqi-satqi" is for sale, "kiraye" is long-term rent.
DEFAULT_SECTION = "alqi-satqi"


@dataclass
class ScrapeOptions:
    base_url: str = "https://bina.az"
    section: str = DEFAULT_SECTION
    query: dict = field(default_factory=dict)
    start_page: int = 1
    max_pages: int = 50
    details: bool = True
    detail_limit: Optional[int] = None
    since: Optional[dt.date] = None
    until: Optional[dt.date] = None
    resume: bool = True
    empty_pages_before_stop: int = 2
    dump_dir: Optional[Path] = None
    fetch: FetchConfig = field(default_factory=FetchConfig)

    def page_url(self, page: int) -> str:
        params = dict(self.query)
        params["page"] = page
        return urljoin(self.base_url + "/", self.section) + "?" + urlencode(params)

    def detail_url(self, listing_id: str) -> str:
        return urljoin(self.base_url + "/", f"items/{listing_id}")


@dataclass
class ScrapeSummary:
    pages_fetched: int = 0
    cards_seen: int = 0
    listings_stored: int = 0
    details_fetched: int = 0
    details_dated: int = 0
    in_range: int = 0
    requests: int = 0
    warnings: list = field(default_factory=list)
    stopped_because: str = ""

    def as_lines(self) -> list[str]:
        lines = [
            f"pages fetched      {self.pages_fetched}",
            f"cards seen         {self.cards_seen}",
            f"listings stored    {self.listings_stored}",
            f"detail pages       {self.details_fetched} ({self.details_dated} yielded a date)",
            f"in date range      {self.in_range}",
            f"http requests      {self.requests}",
            f"stopped because    {self.stopped_because or 'reached max pages'}",
        ]
        return lines + [f"warning: {w}" for w in self.warnings]


def run_scrape(store: Store, options: ScrapeOptions) -> ScrapeSummary:
    fetcher = Fetcher(options.fetch)
    summary = ScrapeSummary()
    run_id = store.start_run(options.section)

    first_url = options.page_url(options.start_page)
    if options.fetch.obey_robots:
        try:
            fetcher.apply_robots_delay(first_url)
            if not fetcher.allowed(first_url):
                summary.warnings.append(
                    f"robots.txt disallows {first_url}. Re-run with --ignore-robots only "
                    f"if you have permission to crawl this path."
                )
                summary.stopped_because = "robots.txt"
                store.finish_run(run_id, 0, 0, 0, "robots.txt disallowed")
                return summary
        except Exception as exc:  # pragma: no cover - network dependent
            summary.warnings.append(f"robots.txt check failed: {exc}")

    done = store.pages_done(options.section) if options.resume else set()
    empty_streak = 0
    page = options.start_page
    last_page = options.start_page + options.max_pages - 1

    while page <= last_page:
        if page in done:
            log.info("page %s already fetched — skipping (use --no-resume to redo)", page)
            page += 1
            continue

        url = options.page_url(page)
        try:
            markup = fetcher.get(url)
        except RobotsDisallowed as exc:
            summary.warnings.append(str(exc))
            summary.stopped_because = "robots.txt"
            break
        except FetchError as exc:
            summary.warnings.append(f"page {page}: {exc}")
            summary.stopped_because = f"fetch failed on page {page}"
            break

        _dump(options.dump_dir, f"list-{options.section}-p{page}.html", markup)

        if looks_like_block_page(markup):
            summary.warnings.append(
                f"page {page} looks like an anti-bot interstitial, not results. "
                f"Slow down (--delay) or stop."
            )
            summary.stopped_because = "blocked"
            break

        listings, report = parse_listing_page(markup, options.base_url, page)
        summary.pages_fetched += 1
        summary.cards_seen += len(listings)
        summary.warnings.extend(f"page {page}: {note}" for note in report.notes)

        store.upsert_listings(listings)
        store.record_page(options.section, page, len(listings))
        summary.listings_stored = store.count()

        if not listings:
            empty_streak += 1
            if empty_streak >= options.empty_pages_before_stop:
                summary.stopped_because = "ran out of results"
                break
        else:
            empty_streak = 0

        page += 1

    if options.details:
        summary_details = _fetch_details(store, fetcher, options)
        summary.details_fetched, summary.details_dated = summary_details

    summary.in_range = sum(
        1 for _ in store.iter_listings(since=options.since, until=options.until)
    )
    summary.requests = fetcher.requests_made
    store.finish_run(
        run_id,
        summary.pages_fetched,
        summary.listings_stored,
        summary.details_fetched,
        summary.stopped_because,
    )
    return summary


def _fetch_details(store: Store, fetcher: Fetcher, options: ScrapeOptions) -> tuple[int, int]:
    ids = store.needs_detail(options.detail_limit)
    if not ids:
        return 0, 0

    log.info("fetching %s detail pages for posting dates", len(ids))
    fetched = dated = 0
    for index, listing_id in enumerate(ids, start=1):
        url = options.detail_url(listing_id)
        try:
            markup = fetcher.get(url)
        except RobotsDisallowed as exc:
            log.warning("%s", exc)
            break
        except FetchError as exc:
            log.warning("detail %s: %s", listing_id, exc)
            continue

        _dump(options.dump_dir, f"item-{listing_id}.html", markup)
        listing = parse_detail_page(markup, listing_id, options.base_url)
        store.upsert_listings([listing])
        fetched += 1
        dated += listing.posted_at is not None

        if index % 50 == 0:
            log.info("  %s/%s detail pages", index, len(ids))

    return fetched, dated


def _dump(directory: Optional[Path], name: str, markup: str) -> None:
    if not directory:
        return
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(markup, encoding="utf-8")
