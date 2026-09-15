import json

import pytest

from bina_scraper.config import load_settings
from bina_scraper.crawl import Crawler, build_search_url
from bina_scraper.fetchers import BlockedError, FetchError, FetchResult
from bina_scraper.store import JsonlStore

ROBOTS_ALLOW_ALL = "User-agent: *\nDisallow:\n"


class FakeFetcher:
    """Serves canned HTML and records every URL requested."""

    def __init__(self, pages: dict[str, str], *, errors: dict[str, Exception] | None = None):
        self.pages = pages
        self.errors = errors or {}
        self.requested: list[str] = []
        self.closed = False

    def get(self, url: str) -> FetchResult:
        self.requested.append(url)
        if url in self.errors:
            raise self.errors[url]
        for key, html in self.pages.items():
            if url.endswith(key) or url == key:
                return FetchResult(url=url, status=200, html=html, final_url=url)
        return FetchResult(url=url, status=404, html="", final_url=url)

    def close(self) -> None:
        self.closed = True


def _settings(tmp_path, **kwargs):
    defaults = dict(
        delay=0.0,
        jitter=0.0,
        output=str(tmp_path / "out.jsonl"),
        respect_robots=False,
        max_pages=1,
    )
    defaults.update(kwargs)
    return load_settings(None, **defaults)


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]


def test_card_only_crawl_writes_one_record_per_card(tmp_path, listing_html):
    settings = _settings(tmp_path, fetch_details=False)
    fetcher = FakeFetcher({"/alqi-satqi": listing_html})
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.pages_fetched == 1
    assert stats.details_fetched == 0
    assert stats.records_written == 2
    records = _records(tmp_path / "out.jsonl")
    assert [r["item_id"] for r in records] == ["4471693", "4471694"]
    assert records[0]["district"] == "Nərimanov"
    assert records[0]["deal_type"] == "sale"
    assert fetcher.closed is True


def test_detail_crawl_merges_card_and_detail(tmp_path, listing_html, item_html):
    settings = _settings(tmp_path, fetch_details=True)
    fetcher = FakeFetcher({"/alqi-satqi": listing_html, "/items/4471693": item_html})
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.details_fetched == 2
    records = {r["item_id"]: r for r in _records(tmp_path / "out.jsonl")}
    full = records["4471693"]
    assert full["amenities"] == ["Kombi", "Mebel", "Kondisioner"]
    assert full["latitude"] == 40.4093
    # The second item has no detail fixture (404, empty body) so its fields come
    # from the card via merge_stub.
    assert records["4471694"]["price"] == 1250000.0


def test_max_items_stops_early(tmp_path, listing_html):
    settings = _settings(tmp_path, fetch_details=False, max_items=1)
    stats = Crawler(settings, fetcher=FakeFetcher({"/alqi-satqi": listing_html})).run()
    assert stats.records_written == 1


def test_pagination_walks_the_page_parameter(tmp_path, listing_html):
    page2 = listing_html.replace("4471693", "5000001").replace("4471694", "5000002")
    fetcher = FakeFetcher({"?page=2": page2, "/alqi-satqi": listing_html})
    settings = _settings(tmp_path, fetch_details=False, max_pages=2)
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.pages_fetched == 2
    assert stats.records_written == 4
    assert fetcher.requested == [
        "https://bina.az/alqi-satqi",
        "https://bina.az/alqi-satqi?page=2",
    ]


def test_pagination_stops_when_a_page_repeats_itself(tmp_path, listing_html):
    """An out-of-range page clamped back to page 1 must not loop."""
    fetcher = FakeFetcher({"/alqi-satqi": listing_html})  # every page is page 1
    settings = _settings(tmp_path, fetch_details=False, max_pages=10)
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.pages_fetched == 2  # page 1, then the repeat that stops it
    assert stats.records_written == 2


def test_follow_next_link_mode_stops_at_the_last_page(tmp_path, listing_html):
    page2 = listing_html.replace("4471693", "5000001").replace("4471694", "5000002")
    page2 = page2.replace('<a class="next_page" rel="next" href="/alqi-satqi?page=2">Növbəti</a>', "")
    fetcher = FakeFetcher({"?page=2": page2, "/alqi-satqi": listing_html})
    settings = _settings(tmp_path, fetch_details=False, max_pages=10, follow_next_link=True)
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.pages_fetched == 2
    assert stats.records_written == 4


def test_duplicate_across_pages_is_written_once(tmp_path, listing_html):
    """One listing shared between two pages must be written once."""
    page2 = listing_html.replace("4471694", "5000002")  # keeps 4471693, adds a new one
    fetcher = FakeFetcher({"?page=2": page2, "/alqi-satqi": listing_html})
    settings = _settings(tmp_path, fetch_details=False, max_pages=2)
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.records_written == 3
    assert stats.skipped_duplicates == 1


def test_blocked_listing_page_stops_the_run(tmp_path):
    settings = _settings(tmp_path, fetch_details=False)
    error = BlockedError("https://bina.az/alqi-satqi", "blocked", status=403)
    fetcher = FakeFetcher({}, errors={"https://bina.az/alqi-satqi": error})
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.blocked is True
    assert stats.records_written == 0


def test_blocked_detail_page_stops_without_raising(tmp_path, listing_html):
    settings = _settings(tmp_path, fetch_details=True)
    error = BlockedError("https://bina.az/items/4471693", "blocked", status=403)
    fetcher = FakeFetcher(
        {"/alqi-satqi": listing_html}, errors={"https://bina.az/items/4471693": error}
    )
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.blocked is True
    # It must not keep requesting further detail pages after a block.
    assert "https://bina.az/items/4471694" not in fetcher.requested


def test_a_single_failed_detail_page_does_not_end_the_run(tmp_path, listing_html):
    settings = _settings(tmp_path, fetch_details=True)
    error = FetchError("https://bina.az/items/4471693", "timeout")
    fetcher = FakeFetcher(
        {"/alqi-satqi": listing_html}, errors={"https://bina.az/items/4471693": error}
    )
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.errors == 1
    assert stats.records_written == 1  # the other listing still lands


def test_empty_results_page_ends_the_run(tmp_path):
    settings = _settings(tmp_path, fetch_details=False, max_pages=5)
    fetcher = FakeFetcher({"/alqi-satqi": "<html><body>Nəticə tapılmadı</body></html>"})
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.pages_fetched == 1
    assert stats.records_written == 0


def test_robots_disallow_prevents_any_fetch(tmp_path, listing_html):
    settings = _settings(tmp_path, fetch_details=False, respect_robots=True)
    fetcher = FakeFetcher(
        {"/robots.txt": "User-agent: *\nDisallow: /alqi-satqi\n", "/alqi-satqi": listing_html}
    )
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.pages_fetched == 0
    assert stats.records_written == 0


def test_robots_allow_permits_the_crawl(tmp_path, listing_html):
    settings = _settings(tmp_path, fetch_details=False, respect_robots=True)
    fetcher = FakeFetcher({"/robots.txt": ROBOTS_ALLOW_ALL, "/alqi-satqi": listing_html})
    stats = Crawler(settings, fetcher=fetcher).run()
    assert stats.records_written == 2


def test_unreadable_robots_refuses_by_default(tmp_path, listing_html):
    """Strict mode: no robots.txt answer means no crawl."""
    settings = _settings(tmp_path, fetch_details=False, respect_robots=True)
    fetcher = FakeFetcher(
        {"/alqi-satqi": listing_html},
        errors={"https://bina.az/robots.txt": FetchError("robots", "connection reset")},
    )
    stats = Crawler(settings, fetcher=fetcher).run()
    assert stats.pages_fetched == 0


def test_unique_mode_skips_previously_written_ids(tmp_path, listing_html):
    out = tmp_path / "out.jsonl"
    with JsonlStore(out, mode="unique") as store:
        store.write({"item_id": "4471693"})
    settings = _settings(tmp_path, fetch_details=False, output=str(out), store_mode="unique")
    fetcher = FakeFetcher({"/alqi-satqi": listing_html})
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.skipped_duplicates == 1
    assert stats.records_written == 1
    # A known listing must not cost a detail request in unique mode.
    assert "https://bina.az/items/4471693" not in fetcher.requested


def test_save_html_dir_keeps_raw_pages(tmp_path, listing_html):
    raw = tmp_path / "raw"
    settings = _settings(tmp_path, fetch_details=False, save_html_dir=str(raw))
    Crawler(settings, fetcher=FakeFetcher({"/alqi-satqi": listing_html})).run()
    assert list(raw.glob("listing_*.html"))


@pytest.mark.parametrize(
    "deal_type, expected_path",
    [("sale", "/alqi-satqi"), ("rent", "/kiraye"), ("rent_daily", "/gunluk-kiraye")],
)
def test_search_url_per_deal_type(tmp_path, deal_type, expected_path):
    settings = _settings(tmp_path, deal_type=deal_type)
    assert build_search_url(settings, 1) == f"https://bina.az{expected_path}"
    assert build_search_url(settings, 2).endswith("page=2")


def test_block_while_reading_robots_is_reported_as_a_block(tmp_path, listing_html):
    """A 403 on robots.txt is the site refusing us, not a robots rule."""
    settings = _settings(tmp_path, fetch_details=False, respect_robots=True)
    error = BlockedError("https://bina.az/robots.txt", "blocked by the site", status=403)
    fetcher = FakeFetcher({"/alqi-satqi": listing_html}, errors={"https://bina.az/robots.txt": error})
    stats = Crawler(settings, fetcher=fetcher).run()

    assert stats.blocked is True
    assert stats.pages_fetched == 0


# --- observation log across repeated crawls --------------------------------


def test_second_crawl_appends_a_new_observation(tmp_path, listing_html):
    """A re-crawl must record the new price, not skip the listing it knows."""
    out = tmp_path / "out.jsonl"
    settings = _settings(tmp_path, fetch_details=False, output=str(out))

    first = Crawler(settings, fetcher=FakeFetcher({"/alqi-satqi": listing_html})).run()
    assert first.records_written == 2

    cheaper = listing_html.replace("185 000", "175 000")
    second = Crawler(settings, fetcher=FakeFetcher({"/alqi-satqi": cheaper})).run()
    assert second.records_written == 2
    assert second.skipped_duplicates == 0

    rows = _records(out)
    assert len(rows) == 4
    prices = [r["price"] for r in rows if r["item_id"] == "4471693"]
    assert prices == [185000.0, 175000.0]


def test_changes_mode_skips_an_unchanged_listing(tmp_path, listing_html):
    out = tmp_path / "out.jsonl"
    settings = _settings(tmp_path, fetch_details=False, output=str(out), store_mode="changes")

    first = Crawler(settings, fetcher=FakeFetcher({"/alqi-satqi": listing_html})).run()
    assert first.records_written == 2

    second = Crawler(settings, fetcher=FakeFetcher({"/alqi-satqi": listing_html})).run()
    assert second.records_written == 0
    assert second.unchanged == 2
    assert len(_records(out)) == 2

    cheaper = listing_html.replace("185 000", "175 000")
    third = Crawler(settings, fetcher=FakeFetcher({"/alqi-satqi": cheaper})).run()
    assert third.records_written == 1  # only the listing whose price moved
    assert third.unchanged == 1


def test_records_carry_a_content_hash(tmp_path, listing_html):
    settings = _settings(tmp_path, fetch_details=False)
    Crawler(settings, fetcher=FakeFetcher({"/alqi-satqi": listing_html})).run()
    rows = _records(tmp_path / "out.jsonl")
    assert all(len(r["content_hash"]) == 32 for r in rows)
    assert rows[0]["content_hash"] != rows[1]["content_hash"]


def test_observation_mode_still_fetches_details_on_a_recrawl(tmp_path, listing_html, item_html):
    """Detail pages must be re-fetched, or a price change is never seen."""
    out = tmp_path / "out.jsonl"
    settings = _settings(tmp_path, fetch_details=True, output=str(out))
    pages = {"/alqi-satqi": listing_html, "/items/4471693": item_html}

    Crawler(settings, fetcher=FakeFetcher(pages)).run()
    second_fetcher = FakeFetcher(pages)
    Crawler(settings, fetcher=second_fetcher).run()

    assert "https://bina.az/items/4471693" in second_fetcher.requested
