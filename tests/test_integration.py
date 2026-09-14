"""End-to-end test against a local HTTP server standing in for bina.az.

The unit tests parse saved markup; this one exercises the parts they cannot —
real sockets, robots.txt, pagination, the resume bookkeeping, the detail pass
and the report — without touching the network.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bina.fetch import FetchConfig
from bina.report import build_report
from bina.scrape import ScrapeOptions, run_scrape
from bina.store import Store

PAGES_WITH_RESULTS = 3
CARDS_PER_PAGE = 5

ROBOTS = "User-agent: *\nDisallow: /admin\nAllow: /\n"

CARD = """
<div class="items-i">
  <a href="/items/{id}" class="item_link">
    <div class="card">
      <div class="card_params">
        <div class="card_params-price"><span class="price-val">{price}</span> <span class="price-cur">AZN</span></div>
        <div class="card_params-name">{rooms} otaqlı yeni tikili</div>
        <ul class="name_location"><li class="location">{district} r. {metro} m.</li></ul>
        <table class="parameters"><tr><td>{rooms} otaq</td><td>{area} m²</td><td>4/12 mərtəbə</td></tr></table>
      </div>
    </div>
  </a>
</div>
"""

DETAIL = """<!doctype html>
<html><head><link rel="canonical" href="/items/{id}"></head><body>
  <h1>{rooms} otaqlı yeni tikili</h1>
  <div class="product-price">{price} AZN</div>
  <div class="product-properties"><span>{rooms} otaq</span><span>{area} m²</span></div>
  <div class="product-map__address">Bakı, {district} r., {metro} m.</div>
  <div class="product-statistics">
    <p>Elanın nömrəsi: {id}</p>
    <p>Elan yaradıldı: {day} {month} {year}</p>
  </div>
</body></html>
"""

DISTRICTS = ["Nəsimi", "Yasamal", "Xətai", "Səbail", "Binəqədi"]
MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun"]


def listing_values(listing_id: int) -> dict:
    index = listing_id % 5
    return {
        "id": listing_id,
        "price": f"{100 + index * 25} 000",
        "area": 60 + index * 15,
        "rooms": 1 + index % 4,
        "district": DISTRICTS[index],
        "metro": "Xətai",
        "day": 1 + index * 3,
        "month": MONTHS[index],
        "year": 2026,
    }


class FakeBinaHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - required name
        parsed = urlparse(self.path)

        if parsed.path == "/robots.txt":
            return self._send(ROBOTS, "text/plain")

        if parsed.path == "/alqi-satqi":
            page = int(parse_qs(parsed.query).get("page", ["1"])[0])
            if page > PAGES_WITH_RESULTS:
                return self._send("<html><body><div class='products'></div></body></html>")
            first = 1000 + (page - 1) * CARDS_PER_PAGE
            cards = "".join(
                CARD.format(**listing_values(first + offset)) for offset in range(CARDS_PER_PAGE)
            )
            return self._send(f"<html><body><div class='products'>{cards}</div></body></html>")

        if parsed.path.startswith("/items/"):
            listing_id = int(parsed.path.rsplit("/", 1)[1])
            return self._send(DETAIL.format(**listing_values(listing_id)))

        self.send_error(404)

    def _send(self, body: str, content_type: str = "text/html; charset=utf-8"):
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence the test output
        pass


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # urllib would otherwise send a loopback request to the agent proxy.
        cls._old_no_proxy = os.environ.get("no_proxy")
        os.environ["no_proxy"] = "127.0.0.1,localhost"

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBinaHandler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        if cls._old_no_proxy is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = cls._old_no_proxy

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.sqlite3")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def options(self, **overrides) -> ScrapeOptions:
        settings = dict(
            base_url=self.base_url,
            section="alqi-satqi",
            max_pages=6,
            details=True,
            since=dt.date(2026, 1, 1),
            until=dt.date(2026, 12, 31),
            fetch=FetchConfig(delay=0.0, jitter=0.0, obey_robots=True),
        )
        settings.update(overrides)
        return ScrapeOptions(**settings)

    def test_full_run_collects_every_listing_with_dates(self):
        summary = run_scrape(self.store, self.options())

        expected = PAGES_WITH_RESULTS * CARDS_PER_PAGE
        self.assertEqual(summary.cards_seen, expected)
        self.assertEqual(summary.listings_stored, expected)
        self.assertEqual(summary.details_fetched, expected)
        self.assertEqual(summary.details_dated, expected)
        self.assertEqual(summary.stopped_because, "ran out of results")
        self.assertEqual(summary.warnings, [])

        rows = list(self.store.iter_listings())
        self.assertEqual(len(rows), expected)
        for row in rows:
            self.assertIsNotNone(row.price, row.listing_id)
            self.assertIsNotNone(row.area, row.listing_id)
            self.assertIsNotNone(row.rooms, row.listing_id)
            self.assertTrue(row.district, row.listing_id)
            self.assertIsNotNone(row.posted_at, row.listing_id)
            self.assertEqual(row.date_source, "created")

    def test_a_second_run_redoes_no_work(self):
        run_scrape(self.store, self.options())
        before = self.store.count()

        summary = run_scrape(self.store, self.options())

        # Recorded pages are skipped and every listing already has its date,
        # so the only page fetched is the boundary probe past the last known
        # page — where new listings would appear.
        self.assertLessEqual(summary.pages_fetched, 1)
        self.assertEqual(summary.cards_seen, 0)
        self.assertEqual(summary.details_fetched, 0)
        self.assertEqual(self.store.count(), before)

    def test_detail_limit_splits_the_work_across_runs(self):
        first = run_scrape(self.store, self.options(detail_limit=4))
        self.assertEqual(first.details_fetched, 4)

        remaining = len(self.store.needs_detail())
        self.assertEqual(remaining, PAGES_WITH_RESULTS * CARDS_PER_PAGE - 4)

        second = run_scrape(self.store, self.options(detail_limit=4))
        # Every page with results is already recorded; a resumed run only
        # re-probes the boundary past the last known page, where new listings
        # would show up.
        self.assertLessEqual(second.pages_fetched, 1)
        self.assertEqual(second.details_fetched, 4)

    def test_cards_only_run_leaves_the_dates_unset(self):
        summary = run_scrape(self.store, self.options(details=False))
        self.assertEqual(summary.details_fetched, 0)
        self.assertEqual(len(self.store.needs_detail()), PAGES_WITH_RESULTS * CARDS_PER_PAGE)
        self.assertEqual(len(list(self.store.iter_listings())), 0)  # none dated
        self.assertEqual(
            len(list(self.store.iter_listings(include_undated=True))),
            PAGES_WITH_RESULTS * CARDS_PER_PAGE,
        )

    def test_robots_disallowed_section_stops_the_run(self):
        summary = run_scrape(self.store, self.options(section="admin"))
        self.assertEqual(summary.stopped_because, "robots.txt")
        self.assertEqual(summary.pages_fetched, 0)
        self.assertTrue(any("robots.txt" in warning for warning in summary.warnings))

    def test_the_report_builds_from_the_scraped_rows(self):
        run_scrape(self.store, self.options())
        html = build_report(
            list(self.store.iter_listings()),
            since=dt.date(2026, 1, 1),
            until=dt.date(2026, 12, 31),
        )
        self.assertIn("Median price per m² by district", html)
        self.assertIn("Nəsimi", html)
        self.assertGreaterEqual(html.count("<svg"), 3)


if __name__ == "__main__":
    unittest.main()
