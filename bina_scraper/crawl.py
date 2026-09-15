"""The crawl loop: pages -> cards -> detail pages -> JSONL."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

from . import selectors as sel
from .config import Settings
from .fetchers import BlockedError, FetchError, Fetcher, build_fetcher
from .models import Listing, ListingStub
from .parse.detail import parse_detail
from .parse.listing import find_next_page_url, parse_listing_page
from .parse.normalize import split_location
from .robots import RobotsPolicy
from .store import JsonlStore

log = logging.getLogger(__name__)


@dataclass
class CrawlStats:
    pages_fetched: int = 0
    cards_seen: int = 0
    details_fetched: int = 0
    records_written: int = 0
    skipped_duplicates: int = 0
    errors: int = 0
    blocked: bool = False

    def summary(self) -> str:
        return (
            f"pages={self.pages_fetched} cards={self.cards_seen} "
            f"details={self.details_fetched} written={self.records_written} "
            f"dupes={self.skipped_duplicates} errors={self.errors}"
            + (" BLOCKED" if self.blocked else "")
        )


def build_search_url(settings: Settings, page: int) -> str:
    """The search-results URL for one page."""
    params = dict(settings.query_params)
    if page > 1:
        params["page"] = page
    url = urljoin(settings.base_url, settings.search_url_path())
    return f"{url}?{urlencode(params)}" if params else url


def _stub_to_listing(stub: ListingStub, deal_type: str | None) -> Listing:
    """Build a record from a card alone, for --no-details runs."""
    listing = Listing(
        item_id=stub.item_id,
        url=stub.url,
        scraped_at=datetime.now(timezone.utc).isoformat(),
        deal_type=deal_type,
    )
    listing.properties["_selector_revision"] = sel.SELECTOR_REVISION
    listing.properties["_source"] = "card_only"
    listing.merge_stub(stub)
    parts = split_location(stub.location)
    listing.city, listing.district, listing.metro = parts["city"], parts["district"], parts["metro"]
    listing.address = parts["address"]
    return listing


class Crawler:
    def __init__(self, settings: Settings, fetcher: Fetcher | None = None, store: JsonlStore | None = None):
        self.settings = settings
        self.fetcher = fetcher or build_fetcher(settings)
        self.store = store or JsonlStore(settings.output, resume=settings.resume)
        self.robots = RobotsPolicy(
            settings.effective_user_agent(), enabled=settings.respect_robots
        )
        self.stats = CrawlStats()
        self._robots_delay: float | None = None

    # -- politeness ---------------------------------------------------------
    def _sleep(self) -> None:
        base = self.settings.delay
        if self._robots_delay is not None:
            base = max(base, self._robots_delay)
        if base <= 0 and self.settings.jitter <= 0:
            return
        time.sleep(base + random.uniform(0, self.settings.jitter))

    def _allowed(self, url: str) -> bool:
        try:
            allowed = self.robots.allows(url, self.fetcher)
        except BlockedError as exc:
            # Blocked while reading robots.txt: the site is refusing us, so
            # report that rather than a robots decision we never got to make.
            self.stats.blocked = True
            log.error("%s", exc)
            return False
        if not allowed:
            log.error("robots policy does not permit %s; skipping", url)
            return False
        if self._robots_delay is None:
            self._robots_delay = self.robots.crawl_delay(url, self.fetcher)
            if self._robots_delay:
                log.info("honouring robots Crawl-delay of %ss", self._robots_delay)
        return True

    def _save_html(self, url: str, html: str, kind: str) -> None:
        if not self.settings.save_html_dir:
            return
        directory = Path(self.settings.save_html_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = url.rstrip("/").split("/")[-1].replace("?", "_")[:80] or "index"
        (directory / f"{kind}_{stamp}.html").write_text(html, encoding="utf-8")

    # -- crawl --------------------------------------------------------------
    def run(self) -> CrawlStats:
        self.store.open()
        try:
            self._run_pages()
        finally:
            self.store.close()
            self.fetcher.close()
        log.info("done: %s", self.stats.summary())
        return self.stats

    def _run_pages(self) -> None:
        """Walk search-result pages.

        Pagination is driven by the ``page`` query parameter rather than the
        "next" link, so it does not depend on a selector that may go stale; the
        link is only used when ``follow_next_link`` is on. The run ends on the
        first page that yields no cards, or whose cards were all seen earlier in
        this run (which is what a site clamping an out-of-range page to the last
        one looks like).
        """
        seen_this_run: set[str] = set()
        page_number = self.settings.start_page
        link_url: str | None = None

        for page_index in range(self.settings.max_pages):
            url = link_url or build_search_url(self.settings, page_number)
            if not self._allowed(url):
                return
            log.info("page %s/%s: %s", page_index + 1, self.settings.max_pages, url)
            try:
                result = self.fetcher.get(url)
            except BlockedError as exc:
                self.stats.blocked = True
                log.error("%s", exc)
                return
            except FetchError as exc:
                self.stats.errors += 1
                log.error("could not fetch %s: %s", url, exc)
                return

            self.stats.pages_fetched += 1
            self._save_html(url, result.html, "listing")
            stubs = parse_listing_page(result.html, self.settings.base_url)
            if not stubs:
                if self.stats.pages_fetched == 1:
                    log.warning(
                        "no cards matched on %s — either the search returned nothing "
                        "or the card selectors are stale; run verify-selectors on a "
                        "saved copy of this page",
                        url,
                    )
                else:
                    log.info("page %s has no listings; stopping", url)
                return

            page_ids = {stub.item_id for stub in stubs}
            if page_ids and page_ids <= seen_this_run:
                log.info("page %s repeats listings already seen this run; stopping", url)
                return
            seen_this_run |= page_ids
            self.stats.cards_seen += len(stubs)

            try:
                if self._process_stubs(stubs) is False:
                    return
            except BlockedError:
                # Already logged where it was raised; stop rather than keep
                # knocking on a door the site has closed.
                return

            page_number += 1
            link_url = None
            if self.settings.follow_next_link:
                next_url = find_next_page_url(result.html, self.settings.base_url)
                if next_url is None:
                    log.info("no next-page link on %s; stopping", url)
                    return
                if next_url == url:
                    log.info("next-page link on %s points at itself; stopping", url)
                    return
                link_url = next_url
            self._sleep()

    def _process_stubs(self, stubs: list[ListingStub]) -> bool:
        """Write records for a page's cards. False means stop the crawl."""
        for stub in stubs:
            if self.store.has(stub.item_id):
                self.stats.skipped_duplicates += 1
                continue
            if self.settings.max_items is not None and self.stats.records_written >= self.settings.max_items:
                log.info("reached max_items=%s", self.settings.max_items)
                return False

            if self.settings.fetch_details:
                listing = self._fetch_detail(stub)
                if listing is None:
                    continue
            else:
                listing = _stub_to_listing(stub, self.settings.deal_type)

            if self.store.write(listing.to_dict()):
                self.stats.records_written += 1
            else:
                self.stats.skipped_duplicates += 1
        return True

    def _fetch_detail(self, stub: ListingStub) -> Listing | None:
        if not self._allowed(stub.url):
            return None
        try:
            result = self.fetcher.get(stub.url)
        except BlockedError as exc:
            self.stats.blocked = True
            log.error("%s", exc)
            raise
        except FetchError as exc:
            self.stats.errors += 1
            log.warning("skipping %s: %s", stub.url, exc)
            return None

        self.stats.details_fetched += 1
        self._save_html(stub.url, result.html, "item")
        listing = parse_detail(result.html, result.final_url or stub.url, item_id=stub.item_id)
        listing.deal_type = listing.deal_type or self.settings.deal_type
        listing.merge_stub(stub)
        self._sleep()
        return listing
