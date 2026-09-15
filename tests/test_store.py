import datetime as dt
import tempfile
import unittest
from pathlib import Path

from bina.models import Listing
from bina.store import Store, export_csv


def listing(listing_id="1", **kwargs) -> Listing:
    base = dict(
        url=f"https://bina.az/items/{listing_id}",
        price=100000.0,
        currency="AZN",
        area=80.0,
        rooms=3,
        location_raw="Nəsimi r.",
        district="Nəsimi",
    )
    base.update(kwargs)
    return Listing(listing_id=listing_id, **base)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.sqlite3")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_roundtrip(self):
        self.store.upsert_listings([listing("1", posted_at=dt.date(2026, 5, 1))])
        rows = list(self.store.iter_listings())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].price, 100000.0)
        self.assertEqual(rows[0].posted_at, dt.date(2026, 5, 1))
        self.assertEqual(rows[0].district, "Nəsimi")

    def test_upsert_is_idempotent(self):
        self.store.upsert_listings([listing("1", posted_at=dt.date(2026, 5, 1))])
        self.store.upsert_listings([listing("1", posted_at=dt.date(2026, 5, 1))])
        self.assertEqual(self.store.count(), 1)

    def test_a_card_only_recrawl_does_not_erase_the_date(self):
        self.store.upsert_listings(
            [listing("1", posted_at=dt.date(2026, 5, 1), date_source="created")]
        )
        # A later card-only pass has no date to offer.
        self.store.upsert_listings([listing("1", posted_at=None, date_source="")])
        row = next(iter(self.store.iter_listings()))
        self.assertEqual(row.posted_at, dt.date(2026, 5, 1))
        self.assertEqual(row.date_source, "created")

    def test_date_range_filter(self):
        self.store.upsert_listings(
            [
                listing("old", posted_at=dt.date(2025, 1, 1)),
                listing("mid", posted_at=dt.date(2026, 5, 1)),
                listing("new", posted_at=dt.date(2026, 9, 1)),
            ]
        )
        rows = self.store.iter_listings(since=dt.date(2026, 1, 1), until=dt.date(2026, 6, 1))
        self.assertEqual([row.listing_id for row in rows], ["mid"])

    def test_undated_rows_are_excluded_by_default(self):
        self.store.upsert_listings([listing("1"), listing("2", posted_at=dt.date(2026, 5, 1))])
        self.assertEqual(len(list(self.store.iter_listings())), 1)
        self.assertEqual(len(list(self.store.iter_listings(include_undated=True))), 2)

    def test_undated_rows_can_be_included_with_a_range(self):
        self.store.upsert_listings([listing("1"), listing("2", posted_at=dt.date(2026, 5, 1))])
        rows = self.store.iter_listings(
            since=dt.date(2026, 1, 1), until=dt.date(2026, 6, 1), include_undated=True
        )
        self.assertEqual(sorted(row.listing_id for row in rows), ["1", "2"])

    def test_needs_detail_lists_only_undated_rows(self):
        self.store.upsert_listings(
            [listing("1"), listing("2", posted_at=dt.date(2026, 5, 1), detail_fetched=True)]
        )
        self.assertEqual(self.store.needs_detail(), ["1"])

    def test_page_bookkeeping_supports_resume(self):
        self.store.record_page("alqi-satqi", 1, 24)
        self.store.record_page("alqi-satqi", 2, 24)
        self.assertEqual(self.store.pages_done("alqi-satqi"), {1, 2})
        self.assertEqual(self.store.pages_done("kiraye"), set())

    def test_run_bookkeeping(self):
        run_id = self.store.start_run("alqi-satqi")
        self.store.finish_run(run_id, pages=3, listings=70, details=70, note="done")
        row = self.store.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        self.assertEqual(row["pages"], 3)
        self.assertEqual(row["note"], "done")

    def test_csv_export(self):
        self.store.upsert_listings([listing("1", posted_at=dt.date(2026, 5, 1))])
        path = Path(self.tmp.name) / "out.csv"
        count = export_csv(self.store.iter_listings(), path)
        self.assertEqual(count, 1)
        text = path.read_text(encoding="utf-8")
        self.assertIn("price_per_m2", text)
        self.assertIn("1250.00", text)  # 100000 / 80


class ListingModelTests(unittest.TestCase):
    def test_price_per_m2(self):
        self.assertEqual(listing("1").price_per_m2, 1250.0)

    def test_price_per_m2_needs_both_values(self):
        self.assertIsNone(listing("1", area=None).price_per_m2)
        self.assertIsNone(listing("1", price=None).price_per_m2)
        self.assertIsNone(listing("1", area=0.0).price_per_m2)

    def test_merge_prefers_non_empty_values(self):
        card = listing("1", rooms=None, posted_at=None)
        detail = Listing(listing_id="1", rooms=4, posted_at=dt.date(2026, 5, 1))
        merged = card.merge(detail)
        self.assertEqual(merged.rooms, 4)
        self.assertEqual(merged.posted_at, dt.date(2026, 5, 1))
        self.assertEqual(merged.price, 100000.0)  # kept from the card


if __name__ == "__main__":
    unittest.main()
